"""Real selected-minion entries, original residence, and ordinary copy/resurrection writers."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json, unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_physical_copy_control as native
from hs_sim.engine import EndTurn, Game, PlayCard, PlayerSetup, ResolutionError, Scenario, SnapshotError
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy,
    GainArmor, GrantKeyword, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence,
    Transform, TriggerDeathrattles)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.model import (BattlecryRepeatSpec, CardDefinition, CardType, DeathrattleMemory,
    DeathrattleRepeatSpec, Keyword, NativeDeathrattleSpec, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.selected_minion_memory import validate_subject
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial, validate_request
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.local_pool_format import build_cn37_local_pool_format

KAAHRJ, CELESTIA, NAMELESS, NAJAK, PLAGUEMAW = native.ROOTS
P = 'k721.'
A, B, TAUNT, TOKEN, SLEEP, BC_REPEAT, DR_REPEAT, QUANTITY = (
    P+x for x in ('a', 'b', 'taunt', 'token', 'sleep', 'bc_repeat', 'dr_repeat', 'quantity'))
KILL, HUSH, BOOST, WOUND, RETURN, CONTROL, FORM, COPY, EARLY, GRANT, SUMMON, DOZE = (
    P+x for x in ('kill', 'hush', 'boost', 'wound', 'return', 'control', 'form', 'copy', 'early', 'grant', 'summon', 'doze'))
WAIT, KILL_NAJAK, FAIL = P+'wait', P+'kill_najak', P+'fail'
CTX = GenerationContext(P+'original-physical-fixture', 'experimental')


@lru_cache(None)
def fixture(role='writer', host=False):
    h = build_cn37_local_pool_format() if host else None
    r = h.registry if h else defaults()
    if not host: native.register_past_physical_copy_control(r)
    meta = metadata(collectible=False, tribes=())
    r.register_behavior(P+'self_buff', lambda c: (Buff(c.source_id, 2, 3, c.source_id), GainArmor(c.player_id, 3)))
    r.register_behavior(P+'token', lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), SummonCause.capture(c)),))
    for cid, attack, health, fields in (
            (A, 2, 6, dict(battlecry=P+'self_buff')),
            (B, 5, 7, {}), (TOKEN, 1, 1, {}),
            (TAUNT, 2, 3, dict(keywords=(Keyword.TAUNT,), deathrattle=P+'token')),
            (SLEEP, 2, 4, dict(dormant_turns=2)),
            (BC_REPEAT, 0, 12, dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (DR_REPEAT, 0, 12, dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),))),
            (QUANTITY, 0, 12, dict(summon_quantities=(SummonQuantitySpec(),)))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack,
            health=health, metadata=meta, **fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HUSH: lambda c: (Silence(c.target_id),),
        BOOST: lambda c: (Buff(c.target_id, 3, 4, c.source_id),),
        WOUND: lambda c: (Damage(c.target_id, 1, c.source_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        FORM: lambda c: (Transform(c.target_id, B),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current', cause=SummonCause.capture(c)),),
        EARLY: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        GRANT: lambda c: (GrantKeyword(c.target_id, Keyword.TAUNT, c.source_id),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(A),), SummonCause.capture(c)),),
        DOZE: lambda c: (MakeDormant(c.target_id, None),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=meta,
            **({'targeting': TargetSpec()} if cid != SUMMON else {})))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K721 deliberate recovery failure')))

    def wait(c):
        event = c.event; target = c.state.entities.get(event.target_id)
        if target is None: return ()
        original = None
        if event.kind == 'control_changed':
            qualifies = event.player_id == 1 and any(
                row.card_id == NAJAK and row.payload_started and not row.completed
                and row.target_id == target.id for row in c.state.battlecry_history)
        elif event.kind == 'transformed':
            old = dict(event.data).get('old_card_id'); qualifies = old in (NAMELESS, CELESTIA)
            if old == NAMELESS:
                original = next(row.target_id for row in reversed(c.state.battlecry_history)
                    if row.card_id == NAMELESS and row.source_id == target.id)
        else:
            row = next((x for x in c.state.resurrection_history if x.entity_id == target.id), None)
            qualifies = row is not None and row.source_id is not None and c.state.entities[row.source_id].card_id == PLAGUEMAW
            if qualifies and Keyword.TAUNT in target.keywords:
                raise ResolutionError('Taunt-free resurrection published a Taunt body before its entry policy')
        if not qualifies: return ()
        options = (
            ChoiceOption('continue', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('fault', 'Fault after random consumption', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, c.player_id))),
        )
        if original is not None: options += (ChoiceOption('bounce', 'Return original selected minion', (ReturnToHand(original),)),)
        return (RequestChoice(c.player_id, options, c.source_id),)

    r.register_behavior(WAIT, wait)
    r.register_card(CardDefinition(WAIT, WAIT, CardType.MINION, health=20, metadata=meta,
        triggers=tuple(TriggerSpec(event, WAIT) for event in ('control_changed', 'transformed', 'minion_summoned'))))

    def kill_najak(c):
        if c.event.player_id != 1: return ()
        rows = [row for row in c.state.battlecry_history if row.card_id == NAJAK and row.payload_started
            and not row.completed and row.target_id == c.event.target_id]
        if not rows: return ()
        return (Destroy(rows[-1].source_id, c.source_id),)

    r.register_behavior(KILL_NAJAK, kill_najak)
    r.register_card(CardDefinition(KILL_NAJAK, KILL_NAJAK, CardType.MINION, health=20, metadata=meta,
        triggers=(TriggerSpec('control_changed', KILL_NAJAK),)))
    r.validate()
    return r, h.context if h else CTX


class PastPhysicalCopyControlTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: fixture(role, mode == 'host')[0])

    def game(self, hand=(), *, board=(), enemy=(), enemy_hand=(), host=False):
        self.mode = 'host' if host else 'small'; r, context = fixture('writer', host)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(TOKEN,)*16,
                mana=40, max_mana=40, mana_cap=40, armor=500),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(TOKEN,)*16,
                mana=40, max_mana=40, mana_cap=40, armor=500)), seed=721, generation_context=context), r)

    def unit(self, g, cid, p=1): return self.entity(g, cid, p, 'board')
    def copies(self, g, cid, p=1):
        return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id == cid]
    def memory(self, g, eid):
        return next(a.deathrattle_memory for a in active_abilities(g.state.entities[eid], 'deathrattle'))
    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1; self.assertLess(count, 25); self.choose(g)
    def fault(self, g):
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), saved)

    def test_complete_original_faces_twelve_primary_responses_and_uncropped_past(self):
        data = native.load_batch()
        self.assertEqual(len(data['original_candidate_ids']), 732)
        self.assertEqual(len(data['official_observations']), 12)
        self.assertFalse(data['complete_past_source_bound'])
        self.assertNotIn('MIS_701', fixture()[0].cards)
        for cid in native.ROOTS:
            self.assertEqual(fixture()[0].card(cid), fixture('independent-reader')[0].card(cid))

    def test_Kaahrj_paid_selection_remembers_original_enemy_and_summons_fresh_base(self):
        g = self.game((BOOST, WOUND, KAAHRJ, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
        self.play(g, BOOST, target); self.play(g, WOUND, target); source = self.play(g, KAAHRJ, target)
        memory = self.memory(g, source); self.assertEqual(memory.selected_subjects[0].target.entity_id, target)
        self.assertEqual(g.state.entities[target].controller, 2); self.play(g, KILL, source)
        fresh = self.unit(g, A)
        self.assertEqual((fresh.attack, fresh.max_health, fresh.damage), (2, 6, 0))
        self.assertNotEqual(fresh.id, target); self.assertEqual(g.state.players[1].mana, 37)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 500)
        self.assertEqual(len(g.state.battlecry_history), 1)

    def test_Kaahrj_accepted_selected_face_survives_later_original_transform_or_death(self):
        for change in (FORM, KILL):
            with self.subTest(change=change):
                g = self.game((KAAHRJ, change, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
                source = self.play(g, KAAHRJ, target); self.play(g, change, target); self.play(g, KILL, source)
                self.assertEqual(len(self.copies(g, A)), 1)
                self.assertEqual(g.state.entities[target].card_id, B if change == FORM else A)

    def test_Kaahrj_each_actual_Battlecry_and_Deathrattle_or_quantity_uses_original_recipe(self):
        for provider in (BC_REPEAT, DR_REPEAT, QUANTITY):
            with self.subTest(provider=provider):
                g = self.game((KAAHRJ, KILL), board=(provider,), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
                self.assertEqual(len(self.memory(g, source).selected_subjects), 2 if provider == BC_REPEAT else 1)
                self.play(g, KILL, source); self.assertEqual(len(self.copies(g, A)), 2)
                self.assertEqual(g.state.players[1].mana, 37)

    def test_Kaahrj_current_copy_preserves_memory_and_new_Deathrattle_controller_receives_body(self):
        g = self.game((KAAHRJ, COPY, HUSH, KILL), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
        self.play(g, COPY, source); duplicate = next(e.id for e in self.copies(g, KAAHRJ) if e.id != source)
        self.assertEqual(self.memory(g, source), self.memory(g, duplicate))
        self.play(g, HUSH, source); self.play(g, KILL, duplicate); self.assertEqual(len(self.copies(g, A)), 1)
        g = self.game((KAAHRJ, CONTROL, KILL), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
        self.play(g, CONTROL, source); self.play(g, KILL, source)
        self.assertEqual(len(self.copies(g, A)), 0); self.assertEqual(len(self.copies(g, A, 2)), 2)

    def test_Kaahrj_silence_and_bounce_clear_old_native_selection_and_no_enemy_is_empty(self):
        for reset in (HUSH, RETURN):
            with self.subTest(reset=reset):
                g = self.game((KAAHRJ, reset, KILL), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
                self.play(g, reset, source)
                if reset == RETURN:
                    self.assertTrue(all(not a.deathrattle_memory.selected_subjects for a in g.state.entities[source].abilities
                        if a.deathrattle_memory is not None))
                else:
                    self.play(g, KILL, source); self.assertEqual(len(self.copies(g, A)), 0)
        g = self.game((KAAHRJ, KILL)); source = self.play(g, KAAHRJ)
        self.assertEqual(self.memory(g, source).selected_subjects, ()); self.play(g, KILL, source)
        self.assertEqual(g.state.players[1].board, [])

    def test_Kaahrj_remembered_subject_snapshot_clone_replay_and_private_DTO(self):
        g = self.game((KAAHRJ, KILL), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
        g = self.portable(g); self.play(g, KILL, source); self.assertEqual(len(self.copies(g, A)), 1)
        for player in (1, 2):
            dto = json.dumps(g.for_player(player).observe())
            self.assertNotIn('selected_subjects', dto); self.assertNotIn('battlecry_id', dto)

    def test_Kaahrj_actual_composite_keeps_printed_recipe_without_original_local_buffs(self):
        from hs_sim.engine.crafted_faces import CraftedMinionRecipe
        from hs_sim.cards.nefarian_crafted_faces import TEMPLATE
        cid = CraftedMinionRecipe(TEMPLATE, 'TIME_045', 'CORE_OG_149').card_id
        g = self.game((KAAHRJ, BOOST, KILL), enemy=(cid,), host=True); target = self.unit(g, cid, 2).id
        self.play(g, BOOST, target); source = self.play(g, KAAHRJ, target)
        self.assertEqual(self.memory(g, source).selected_subjects[0].copy.components, ('TIME_045', 'CORE_OG_149'))
        g = self.portable(g); self.play(g, KILL, source); fresh = self.unit(g, cid)
        self.assertEqual((fresh.attack, fresh.max_health), (4, 7))
        self.assertEqual(fresh.components, ('TIME_045', 'CORE_OG_149'))
        self.assertIn(Keyword.REBORN, fresh.keywords); self.assertIn(Keyword.POISONOUS, fresh.keywords)
        self.assertEqual(len(g.state.battlecry_history), 1)

    def test_Kaahrj_delayed_base_recipe_requires_actual_original_Deathrattle_recipient_and_source(self):
        from hs_sim.engine.allocation_facts import SourceAllocationFact
        g = self.game((KAAHRJ, KILL), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
        self.play(g, KILL, source); request = g.state.card_summon_history[-1].request
        self.assertEqual((request.materials[0].profile, request.materials[0].mode), ('remembered_copy', 'base'))
        hero = g.state.entities[g.state.players[1].hero_id]
        for changes in ({'player_id': 2}, {'cause': replace(request.cause, source=SourceAllocationFact.capture(g.state, hero))}):
            with self.assertRaises(ValueError): validate_request(g.state, g.registry, replace(request, **changes))

    def test_Najak_paid_take_and_death_returns_same_physical_target(self):
        g = self.game((NAJAK, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.assertEqual(g.state.entities[target].controller, 1)
        self.assertEqual(self.memory(g, source).selected_subjects[0].target.controller, 2)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[target].controller, 2)
        self.assertEqual(g.state.players[1].mana, 36)

    def test_Najak_previous_controller_is_independent_of_owner_and_carrier_controller(self):
        g = self.game((CONTROL, NAJAK, CONTROL, KILL), board=(A,)); target = self.unit(g, A).id
        self.play(g, CONTROL, target); self.assertEqual((g.state.entities[target].owner, g.state.entities[target].controller), (1, 2))
        source = self.play(g, NAJAK, target); self.play(g, CONTROL, source); self.play(g, KILL, source)
        self.assertEqual((g.state.entities[target].owner, g.state.entities[target].controller), (1, 2))

    def test_Najak_original_residence_survives_transform_but_not_bounce_and_reentry(self):
        g = self.game((NAJAK, FORM, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.play(g, FORM, target); self.play(g, KILL, source)
        self.assertEqual((g.state.entities[target].card_id, g.state.entities[target].controller), (B, 2))
        g = self.game((NAJAK, RETURN, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.play(g, RETURN, target)
        self.assertIn(target, g.state.players[1].hand); self.play(g, A); self.play(g, KILL, source)
        self.assertEqual(g.state.entities[target].controller, 1)
        self.assertEqual(sum(e.kind == 'control_changed' and e.target_id == target for e in g._events), 1)

    def test_Najak_memory_is_installed_before_control_notification_can_kill_carrier(self):
        g = self.game((NAJAK,), board=(KILL_NAJAK,), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].controller, 2)
        self.assertEqual([dict(e.data)['previous_controller'] for e in g._events if e.kind == 'control_changed'], [2, 1])

    def test_Najak_repeat_does_not_capture_now_friendly_target_or_duplicate_memory(self):
        g = self.game((NAJAK, KILL), board=(BC_REPEAT,), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.assertEqual(len(self.memory(g, source).selected_subjects), 1)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[target].controller, 2)

    def test_Najak_actual_control_wait_recovers_then_ordinary_return_and_rng_rollback(self):
        g = self.game((NAJAK, KILL), board=(WAIT,), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.memory(g, source).selected_subjects), 1)
        g = self.portable(g); self.fault(g); self.finish(g); self.play(g, KILL, source)
        self.assertEqual(g.state.entities[target].controller, 2)

    def test_real_early_Deathrattles_read_same_subject_without_consuming_original_memory(self):
        for cid in (KAAHRJ, NAJAK):
            with self.subTest(card=cid):
                g = self.game((cid, EARLY, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
                source = self.play(g, cid, target); memory = self.memory(g, source)
                self.play(g, EARLY, source); self.assertEqual(self.memory(g, source), memory)
                if cid == KAAHRJ: self.assertEqual(len(self.copies(g, A)), 1)
                else: self.assertEqual(g.state.entities[target].controller, 2)
                self.play(g, KILL, source)
                if cid == KAAHRJ: self.assertEqual(len(self.copies(g, A)), 2)
                else: self.assertEqual(g.state.entities[target].controller, 2)

    def test_Najak_return_to_full_board_uses_existing_control_capacity_writer(self):
        g = self.game((NAJAK, KILL), enemy=(A,)*7, enemy_hand=(TOKEN,)); target = g.state.players[2].board[0]
        source = self.play(g, NAJAK, target); g.apply(EndTurn(1)); self.play(g, TOKEN, player=2)
        g.apply(EndTurn(2)); self.play(g, KILL, source)
        self.assertEqual(len(g.state.players[2].board), 7)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_Najak_returns_original_dormant_resident_and_keeps_existing_full_board_error_explicit(self):
        g = self.game((NAJAK, DOZE, KILL), enemy=(A,)); target = self.unit(g, A, 2).id
        source = self.play(g, NAJAK, target); self.play(g, DOZE, target); g = self.portable(g)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[target].controller, 2)
        self.assertIsNotNone(g.state.entities[target].dormancy)
        g = self.game((NAJAK, DOZE, KILL), enemy=(A,)*7, enemy_hand=(TOKEN,)); target = g.state.players[2].board[0]
        source = self.play(g, NAJAK, target); self.play(g, DOZE, target)
        g.apply(EndTurn(1)); self.play(g, TOKEN, player=2); g.apply(EndTurn(2)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Dormant full-board'): self.play(g, KILL, source)
        self.assertEqual(g.snapshot(), saved)

    def test_Celestia_paid_opponent_play_copies_current_post_Battlecry_body_once(self):
        g = self.game((CELESTIA,), enemy_hand=(A,)); source = self.play(g, CELESTIA)
        g.apply(EndTurn(1)); target = self.play(g, A, player=2)
        body = g.state.entities[source]
        self.assertEqual((body.card_id, body.attack, body.max_health), (A, 4, 9))
        self.assertNotIn(Keyword.STEALTH, body.keywords)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 503)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 500)
        self.assertEqual(len(g.state.battlecry_history), 1); self.assertNotEqual(target, source)

    def test_Celestia_own_minion_and_effect_summon_do_not_trigger(self):
        g = self.game((CELESTIA, A), enemy_hand=(SUMMON,)); source = self.play(g, CELESTIA); self.play(g, A)
        self.assertEqual(g.state.entities[source].card_id, CELESTIA)
        g.apply(EndTurn(1)); self.play(g, SUMMON, player=2)
        self.assertEqual(g.state.entities[source].card_id, CELESTIA)

    def test_Celestia_silence_suppresses_and_real_transform_wait_recovers(self):
        g = self.game((CELESTIA, HUSH), enemy_hand=(A,)); source = self.play(g, CELESTIA)
        self.play(g, HUSH, source); g.apply(EndTurn(1)); self.play(g, A, player=2)
        self.assertEqual(g.state.entities[source].card_id, CELESTIA)
        g = self.game((CELESTIA,), board=(WAIT,), enemy_hand=(A,)); source = self.play(g, CELESTIA)
        g.apply(EndTurn(1)); self.play(g, A, player=2); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.fault(g); self.finish(g); self.assertEqual(g.state.entities[source].attack, 4)

    def test_Nameless_copies_current_abilities_as_four_four_then_silences_original(self):
        g = self.game((NAMELESS, BOOST, WOUND), enemy=(TAUNT,)); target = self.unit(g, TAUNT, 2).id
        self.play(g, BOOST, target); self.play(g, WOUND, target); source = self.play(g, NAMELESS, target)
        body = g.state.entities[source]; original = g.state.entities[target]
        self.assertEqual((body.card_id, body.attack, body.max_health, body.damage), (TAUNT, 4, 4, 0))
        self.assertIn(Keyword.TAUNT, body.keywords); self.assertTrue(active_abilities(body, 'deathrattle'))
        self.assertTrue(original.silenced); self.assertNotIn(Keyword.TAUNT, original.keywords)
        self.assertFalse(active_abilities(original, 'deathrattle')); self.assertEqual(original.attack, 2)
        self.assertEqual(g.state.players[1].mana, 36)

    def test_Nameless_can_choose_friendly_minion_and_no_target_resolves_empty(self):
        g = self.game((NAMELESS,), board=(TAUNT,)); target = self.unit(g, TAUNT).id
        source = self.play(g, NAMELESS, target); self.assertEqual(g.state.entities[source].attack, 4)
        self.assertTrue(g.state.entities[target].silenced)
        g = self.game((NAMELESS,)); source = self.play(g, NAMELESS)
        self.assertEqual(g.state.entities[source].card_id, NAMELESS)

    def test_Nameless_transform_notification_precedes_captured_original_silence_and_recovers(self):
        g = self.game((NAMELESS,), board=(WAIT,), enemy=(TAUNT,)); target = self.unit(g, TAUNT, 2).id
        source = self.play(g, NAMELESS, target); self.assertIsNotNone(g.state.pending_choice)
        self.assertIn(Keyword.TAUNT, g.state.entities[target].keywords)
        g = self.portable(g); self.fault(g); self.finish(g)
        self.assertTrue(g.state.entities[target].silenced); self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)

    def test_Nameless_captured_silence_skips_original_that_left_during_transform_reaction(self):
        g = self.game((NAMELESS,), board=(WAIT,), enemy=(TAUNT,)); target = self.unit(g, TAUNT, 2).id
        source = self.play(g, NAMELESS, target); g = self.portable(g); self.choose(g, 'bounce'); self.finish(g)
        self.assertEqual(g.state.entities[target].zone, Zone.HAND)
        self.assertFalse(g.state.entities[target].silenced); self.assertIn(Keyword.TAUNT, g.state.entities[target].keywords)
        self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)

    def test_Plaguemaw_paid_source_resurrects_base_without_Taunt_and_keeps_other_abilities(self):
        g = self.game((PLAGUEMAW, BOOST, KILL), board=(TAUNT,)); target = self.unit(g, TAUNT).id
        self.play(g, PLAGUEMAW); self.play(g, BOOST, target); self.play(g, KILL, target)
        body = self.unit(g, TAUNT)
        self.assertNotEqual(body.id, target); self.assertEqual((body.attack, body.max_health), (2, 3))
        self.assertNotIn(Keyword.TAUNT, body.keywords); self.assertTrue(active_abilities(body, 'deathrattle'))
        self.assertIn(Keyword.TAUNT, g.state.death_history[0].keywords)
        self.assertEqual(g.state.players[1].mana, 36)

    def test_Plaguemaw_current_granted_Taunt_matches_frozen_death_and_non_Taunt_does_not(self):
        for grant in (False, True):
            with self.subTest(grant=grant):
                g = self.game((GRANT, KILL), board=(PLAGUEMAW, A)); target = self.unit(g, A).id
                if grant: self.play(g, GRANT, target)
                self.play(g, KILL, target); self.assertEqual(len(self.copies(g, A)), int(grant))
                if grant: self.assertNotIn(Keyword.TAUNT, self.unit(g, A).keywords)

    def test_Plaguemaw_opponent_death_and_silenced_source_do_not_resurrect(self):
        g = self.game((KILL,), board=(PLAGUEMAW,), enemy=(TAUNT,)); self.play(g, KILL, self.unit(g, TAUNT, 2).id)
        self.assertEqual(len(self.copies(g, TAUNT)), 0)
        g = self.game((HUSH, KILL), board=(PLAGUEMAW, TAUNT)); self.play(g, HUSH, self.unit(g, PLAGUEMAW).id)
        self.play(g, KILL, self.unit(g, TAUNT).id); self.assertEqual(len(self.copies(g, TAUNT)), 0)

    def test_Plaguemaw_every_quantity_body_is_Taunt_free_before_first_entry_notification(self):
        g = self.game((KILL,), board=(PLAGUEMAW, QUANTITY, WAIT, TAUNT)); target = self.unit(g, TAUNT).id
        self.play(g, KILL, target); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(len(self.copies(g, TAUNT)), 2)
        self.assertTrue(all(Keyword.TAUNT not in e.keywords for e in self.copies(g, TAUNT)))
        self.assertEqual(len(g.state.resurrection_history), 2)

    def test_Plaguemaw_bounce_and_new_play_restores_ordinary_printed_Taunt(self):
        g = self.game((KILL, RETURN), board=(PLAGUEMAW, TAUNT)); self.play(g, KILL, self.unit(g, TAUNT).id)
        target = self.unit(g, TAUNT).id; self.play(g, RETURN, target); self.play(g, TAUNT)
        self.assertIn(Keyword.TAUNT, g.state.entities[target].keywords)

    def test_selected_memory_rejects_wrong_Battlecry_owner_role_future_and_duplicate(self):
        g = self.game((KAAHRJ,), enemy=(A,)); source = self.play(g, KAAHRJ, self.unit(g, A, 2).id)
        memory = self.memory(g, source); subject = memory.selected_subjects[0]
        changes = (
            lambda: replace(subject, battlecry_id=subject.battlecry_id+99),
            lambda: replace(subject, target=replace(subject.target, owner=1)),
            lambda: replace(subject, presence=replace(subject.presence, presence_id=g.state.next_order)),
        )
        for changed in changes:
            with self.assertRaises(ValueError): validate_subject(g.state, g.registry, changed())
        with self.assertRaises(ValueError): replace(memory, selected_subjects=(subject, subject))
        with self.assertRaises(ValueError): replace(memory, spec=NativeDeathrattleSpec('control_return'))
        with self.assertRaises(ValueError): replace(memory, growth_steps=1)
        with self.assertRaises(ValueError): DeathrattleMemory(NativeDeathrattleSpec('summon_growth'), selected_subjects=(subject,))
        for missing in (False, True):
            bad = deepcopy(g.snapshot())
            ability = next(a for a in bad['state']['entities'][str(source)]['abilities'] if a['deathrattle_memory'] is not None)
            if missing: del ability['deathrattle_memory']['selected_subjects']
            else: ability['deathrattle_memory']['selected_subjects'][0]['battlecry_id'] += 99
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture('independent-reader')[0])

    def test_Taunt_free_request_rejects_unattributed_or_unrelated_keyword_recipes(self):
        for changes in ({'remove_keywords': (Keyword.TAUNT,)}, {'remove_keywords': (Keyword.RUSH,)},
                {'remove_keywords': [Keyword.TAUNT]}, {'remove_keywords': (Keyword.TAUNT.value,)}):
            with self.assertRaises(ValueError): ResurrectMinion(1, 1, **changes)

    def test_five_actual_standard_host_entries_execute_real_bodies_with_same_original_candidates(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g = self.game((cid, KILL), board=(TAUNT,) if cid == PLAGUEMAW else (),
                    enemy=(A,) if cid in (KAAHRJ, NAJAK, NAMELESS) else (), enemy_hand=(A,), host=True)
                target = self.unit(g, A, 2).id if cid in (KAAHRJ, NAJAK, NAMELESS) else None
                source = self.play(g, cid, target)
                if cid == KAAHRJ:
                    g = self.portable(g); self.play(g, KILL, source); self.assertEqual(len(self.copies(g, A)), 1)
                elif cid == NAJAK:
                    self.assertEqual(g.state.entities[target].controller, 1); self.play(g, KILL, source)
                    self.assertEqual(g.state.entities[target].controller, 2)
                elif cid == NAMELESS: self.assertEqual(g.state.entities[source].attack, 4)
                elif cid == PLAGUEMAW:
                    self.play(g, KILL, self.unit(g, TAUNT).id); self.assertNotIn(Keyword.TAUNT, self.unit(g, TAUNT).keywords)
                else:
                    g.apply(EndTurn(1)); self.play(g, A, player=2); self.assertEqual(g.state.entities[source].card_id, A)


if __name__ == '__main__': unittest.main()
