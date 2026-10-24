"""Real authored Assemble suffixes summon full-health copies of their deaths."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.copy_materials import validate_scope
from hs_sim.engine.death_self_copies import entry_from_death
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    DestroyBatch, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, DamageKind, DeathrattleRepeatSpec,
    Keyword, Rarity, RewindSpec, SummonQuantitySpec, TargetSpec)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from tools import card_batch as batch

BASE, SPELLCASTER, STALKER = 'TIME_040', 'CATA_483', 'TIME_605'
CHAMPION, COIN = 'CORE_CS2_222', 'GAME_005'
CTX = GenerationContext('k517-reviewed-self-copy-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON)
P = 'fixture.death_self_copy.'
KILL, GROW, WOUND, SWEEP, TRIGGER, GIVE, MUTE, REBORN, BOUNCE = (
    P + s for s in ('kill', 'grow', 'wound', 'sweep', 'trigger', 'give', 'mute', 'reborn', 'bounce'))
WATCH, FAIL, FILL, REPEAT, QUANTITY = (P + s for s in ('watch', 'fail', 'fill', 'repeat', 'quantity'))
RETRY_KILL = P + 'retry_kill'


def face(donor):
    return AssembleRecipe(BASE, donor, 'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k517.' + mode
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        WOUND: lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        SWEEP: lambda c: (DestroyBatch(tuple(c.state.players[c.player_id].board), c.source_id),),
        TRIGGER: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        REBORN: lambda c: (GrantKeyword(c.target_id, Keyword.REBORN, c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        RETRY_KILL: lambda c: (Destroy(c.target_id, c.source_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, metadata=META,
            on_play=cid, targeting=None if cid == SWEEP else
            TargetSpec(kinds=(CardType.MINION,), relation='any'),
            keywords=(Keyword.REWIND,) if cid == RETRY_KILL else (),
            rewind=RewindSpec(1) if cid == RETRY_KILL else None))
    def fail(c):
        raise ResolutionError('deliberate late self-copy failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        if mode not in ('wait', 'fail') or c.event is None or dict(c.event.data).get('copied_from') is None:
            return ()
        target = c.state.entities[c.event.target_id]
        if not target.card_id.startswith('assemble:'):
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, attack=0, health=20,
        metadata=META, triggers=(TriggerSpec('minion_summoned', WATCH),)))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=0, health=20, metadata=META))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, attack=0, health=20,
        metadata=META, deathrattle_repeats=(DeathrattleRepeatSpec(2),)))
    r.register_card(CardDefinition(QUANTITY, QUANTITY, CardType.MINION, attack=0, health=20,
        metadata=META, summon_quantities=(SummonQuantitySpec(2),)))
    r.register_pool(PoolDefinition(POOL_ID, 'four-real-self-copy-materials-v1', CTX.target_id,
        CTX.mode, (PoolMember(BASE), PoolMember(SPELLCASTER), PoolMember(STALKER),
            PoolMember('CORE_GIL_622')), complete=True))
    return r


def rehash(snapshot):
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})


class DeathrattleSelfCopyTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, actor=1, mode='normal', donor=STALKER):
        self.mode = mode
        hero = 'HERO_08' if donor == SPELLCASTER else 'HERO_05'
        setups = tuple(PlayerSetup(hero, hand=hand if p == actor else (),
            board=board if p == actor else (), deck=(COIN,)*16,
            mana=50, max_mana=50, mana_cap=50) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=actor, seed=517,
            generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None, actor=None):
        actor = game.state.active_player if actor is None else actor
        eid = next(i for i in game.state.players[actor].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(actor, eid, target_id=target))
        return eid

    def manufacture(self, game, donor=STALKER):
        self.play(game, FLESH)
        q = game.state.pending_choice
        cid = face(donor)
        option = next(o for o in q.options if o.card_id == cid)
        game.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return cid

    def copies(self, game, cid, actor=1):
        return [game.state.entities[i] for i in game.state.players[actor].board
            if game.state.entities[i].card_id == cid]

    def finish_choice(self, game, key='ok'):
        q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        reader = fixture(self.mode, 'reader')
        if reader is game.registry:
            reader = fixture(self.mode, 'second_reader')
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        return restored

    def test_sources_full_faces_and_only_two_reviewed_pending_timings_change(self):
        from hs_sim.cards.assemble_conditional_spell_damage_fragments import load_batch as conditional
        from hs_sim.cards.assemble_discovery_copy_count_fragments import load_batch as discovery
        r = fixture()
        for data in (conditional(), discovery()):
            for row in data['existing_dependencies']:
                if row['record']['id'] not in (SPELLCASTER, STALKER):
                    continue
                self.assertEqual(batch.canonical(row['record']), row['record_sha256'])
                self.assertEqual(batch.canonical(asdict(r.card(row['record']['id']))), row['definition_sha256'])
                observations = [o for o in data['official_observations'] if o['card_id'] == row['record']['id']]
                self.assertEqual(len(observations), 2)
                for obs in observations:
                    path = Path(obs['response_file'])
                    self.assertEqual(batch.sha(path), obs['response_sha256'])
                    body = json.loads(path.read_text(encoding='utf-8-sig'))
                    self.assertEqual([x for x in body['cards'] if x['id'] == row['record']['dbf_id']], [obs['face']])
                    batch.check_face(row['record'], obs['face'], obs['locale'])
        for cid in (SPELLCASTER, STALKER):
            self.assertIn('deathrattle', r.assemble_templates[cid].suffix.allowed_timings)
            self.assertEqual(r.assemble_templates[cid].suffix.pending_timings, ())
        self.assertEqual(r.assemble_templates['BE_734'].suffix.pending_timings, ('deathrattle', 'end_turn'))

    def test_actual_fleshshape_manufacture_both_bodies_both_players_and_single_payment(self):
        for actor in (1, 2):
            for donor in (SPELLCASTER, STALKER):
                with self.subTest(actor=actor, donor=donor):
                    g = self.game((FLESH, KILL), actor=actor, donor=donor)
                    cid = self.manufacture(g, donor)
                    mana = g.state.players[actor].mana
                    source = self.play(g, cid)
                    rng = g._rng.getstate()
                    self.play(g, KILL, source)
                    bodies = self.copies(g, cid, actor)
                    self.assertEqual(len(bodies), 1)
                    self.assertEqual((bodies[0].attack, bodies[0].health, bodies[0].damage), (8, 5, 0))
                    self.assertNotEqual(bodies[0].id, source)
                    self.assertEqual(bodies[0].origin_entity_id, source)
                    self.assertEqual(g.state.players[actor].mana, mana-5)
                    self.assertEqual(len(g.state.play_history), 3)
                    self.assertEqual(len(g.state.death_history), 1)
                    self.assertEqual(g.state.card_summon_history[-1].request.materials[0].profile, 'death_copy')
                    self.assertFalse(g.state.battlecry_history)
                    self.assertEqual(g._rng.getstate(), rng)
                    self.assertNotIn(Keyword.RUSH, bodies[0].keywords)
                    self.assertNotIn(Keyword.ELUSIVE, bodies[0].keywords)
                    self.assertEqual(g.registry.card(cid).spell_damage, 0)

    def test_current_buffs_copy_at_full_health_and_dead_auras_are_not_baked_in(self):
        g = self.game((FLESH, GROW, WOUND, SWEEP), (CHAMPION,))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, GROW, source)
        self.play(g, WOUND, source)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (11, 9))
        self.play(g, SWEEP)
        copied, = self.copies(g, cid)
        self.assertEqual((copied.attack, copied.health, copied.max_health, copied.damage), (10, 8, 8, 0))
        death = next(d for d in g.state.death_history if d.entity_id == source)
        self.assertEqual((death.attack, death.max_health, death.damage), (11, 9, 2))
        self.assertEqual(copied.components, death.components)

    def test_active_deathrattle_uses_ordinary_live_copy_and_retains_damage(self):
        for donor in (SPELLCASTER, STALKER):
            with self.subTest(donor=donor):
                g = self.game((FLESH, WOUND, TRIGGER), donor=donor)
                cid = self.manufacture(g, donor)
                source = self.play(g, cid)
                self.play(g, WOUND, source)
                self.play(g, TRIGGER, source)
                self.assertEqual(len(self.copies(g, cid)), 2)
                self.assertTrue(all(e.damage == 2 for e in self.copies(g, cid)))
                self.assertFalse(g.state.death_history)
                self.assertEqual(g.state.card_summon_history[-1].request.materials[0].profile, 'board_copy')

    def test_native_epoch_stalker_keeps_its_original_paid_battlecry(self):
        g = self.game((STALKER, SWEEP))
        mana = g.state.players[1].mana
        source = self.play(g, STALKER)
        self.assertEqual(len(self.copies(g, STALKER)), 2)
        self.assertEqual(g.state.players[1].mana, mana-6)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertTrue(all(Keyword.RUSH in e.keywords and Keyword.ELUSIVE in e.keywords
            for e in self.copies(g, STALKER)))
        self.play(g, SWEEP)
        self.assertFalse(self.copies(g, STALKER))
        self.assertEqual(len(g.state.death_history), 2)
        self.assertFalse(g.state.deathrattle_history)

    def test_natural_copy_belongs_to_death_controller_and_keeps_original_owner_fact(self):
        g = self.game((FLESH, GIVE, KILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, GIVE, source)
        self.play(g, KILL, source)
        self.assertFalse(self.copies(g, cid))
        copied, = self.copies(g, cid, 2)
        self.assertEqual((copied.owner, copied.controller), (2, 2))
        death, = g.state.death_history
        self.assertEqual((death.owner, death.controller), (1, 2))
        self.assertEqual((death.copy_source.origin.owner, death.copy_source.origin.controller), (1, 2))

    def test_silence_removes_self_copy_without_erasing_original_death_flags(self):
        g = self.game((FLESH, MUTE, KILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, MUTE, source)
        self.play(g, KILL, source)
        self.assertFalse(self.copies(g, cid))
        self.assertTrue(g.state.death_history[-1].copy_source.silenced)
        self.assertFalse(g.state.card_summon_history)

    def test_original_death_position_is_used_by_the_shared_summon_pipeline(self):
        cid = face(STALKER)
        g = self.game((KILL,), (FILL, cid, FILL))
        source = g.state.players[1].board[1]
        self.play(g, KILL, source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [FILL, cid, FILL])
        self.assertNotEqual(g.state.players[1].board[1], source)

    def test_each_deathrattle_repeat_gets_one_quantity_root_and_same_frozen_material(self):
        g = self.game((FLESH, KILL), (REPEAT, QUANTITY))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, KILL, source)
        self.assertEqual(len(self.copies(g, cid)), 4)
        self.assertEqual(len(g.state.deathrattle_history), 2)
        self.assertTrue(all(r.completed for r in g.state.deathrattle_history))
        roots = g.state.card_summon_history
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0].request.materials, roots[1].request.materials)
        self.assertTrue(all(e.health == 5 and e.attack == 8 for e in self.copies(g, cid)))

    def test_full_board_accepts_one_available_copy_and_does_not_defer_extra_body(self):
        g = self.game((FLESH, KILL, KILL), (QUANTITY, FILL, FILL, FILL, FILL, FILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.play(g, KILL, source)
        self.assertEqual(len(self.copies(g, cid)), 1)
        filler = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == FILL)
        self.play(g, KILL, filler)
        self.assertEqual(len(self.copies(g, cid)), 1)

    def test_original_unconsumed_reborn_is_copied_and_original_reborn_stays_separate(self):
        g = self.game((FLESH, REBORN, KILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, REBORN, source)
        self.play(g, KILL, source)
        bodies = self.copies(g, cid)
        self.assertEqual(len(bodies), 2)
        self.assertEqual(sorted(e.health for e in bodies), [1, 5])
        copied = next(e for e in bodies if e.health == 5)
        self.assertIn(Keyword.REBORN, copied.keywords)
        reborn = next(e for e in bodies if e.health == 1)
        self.assertNotIn(Keyword.REBORN, reborn.keywords)
        self.assertEqual(sum(e.kind == 'minion_reborn' for e in g.events), 1)

    def test_waiting_copy_restores_clones_and_replays_then_actually_continues_both_players(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game((FLESH, KILL), (WATCH,), actor=actor, mode='wait')
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.play(g, KILL, source)
                self.assertEqual(g.state.pending_choice.player_id, actor)
                restored = self.portable(g)
                for game in (g, restored):
                    self.finish_choice(game)
                    self.assertIsNone(game.state.pending_choice)
                    self.assertEqual(len(self.copies(game, cid, actor)), 1)
                    self.assertTrue(game.state.deathrattle_history[-1].completed)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.portable(restored)

    def test_late_choice_failure_rolls_back_whole_continuation_and_accepts_retry(self):
        g = self.game((FLESH, KILL), (WATCH,), mode='wait')
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, KILL, source)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late'):
            self.finish_choice(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.finish_choice(g)
        self.assertEqual(len(self.copies(g, cid)), 1)

    def test_late_reaction_failure_rolls_back_whole_death_payment_and_new_material(self):
        g = self.game((FLESH, KILL), (WATCH,), mode='fail')
        cid = self.manufacture(g)
        source = self.play(g, cid)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late'):
            self.play(g, KILL, source)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(len(self.copies(g, cid)), 1)
        self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.card_summon_history)

    def test_actual_rewind_retires_first_death_copy_and_preserves_closed_original_proofs(self):
        g = self.game((FLESH, RETRY_KILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        mana = g.state.players[1].mana
        self.play(g, RETRY_KILL, source)
        self.portable(g)
        old = g.state.card_summon_history[-1]
        self.finish_choice(g, 'retry')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.card_summon_history), 1)
        current = g.state.card_summon_history[-1]
        self.assertGreater(current.id, old.id)
        self.assertGreater(current.deliveries[0].entity.entity_id, old.deliveries[0].entity.entity_id)
        self.assertEqual(len(self.copies(g, cid)), 1)
        self.assertEqual(g.state.players[1].mana, mana-1)
        self.assertEqual(current.request.materials[0].self_copy_death, g.state.death_history[-1])
        self.portable(g)

    def test_full_death_material_is_private_and_resolved_snapshot_roundtrips(self):
        g = self.game((FLESH, KILL))
        cid = self.manufacture(g)
        self.play(g, KILL, self.play(g, cid))
        self.portable(g)
        for actor in (1, 2):
            text = json.dumps(g.observe(actor))
            self.assertNotIn('copy_source', text)
            self.assertNotIn('next_attachment_id', text)
            self.assertNotIn('death_copy', text)

    def test_current_graveyard_mutation_cannot_replace_original_copy_material(self):
        g = self.game((FLESH, KILL))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, KILL, source)
        death = g.state.death_history[-1]
        material = entry_from_death(death)
        state = deepcopy(g.state)
        # White-box material validation: this is not claimed as a gameplay move.
        state.entities[source].card_id = FILL
        state.entities[source].base_attack = 99
        state.entities[source].damage = 0
        state.entities[source].abilities.clear()
        validate_scope(state, g.registry, material)
        self.assertEqual(entry_from_death(death), material)
        self.assertEqual((material.card_id, material.local.base_attack), (cid, 6))

    def test_forged_copy_local_fields_and_foreign_death_are_rejected(self):
        g = self.game((FLESH, KILL))
        cid = self.manufacture(g)
        self.play(g, KILL, self.play(g, cid))
        material = g.state.card_summon_history[-1].request.materials[0]
        for kwargs in ({'local': replace(material.local, damage=1)},
                {'local': replace(material.local, base_attack=99)}, {'mode': 'base'},
                {'self_copy_death': None}, {'captured_action': material.captured_action+1}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(ValueError):
                replace(material, **kwargs)
        forged = replace(material, self_copy_death=replace(material.self_copy_death, id=material.self_copy_death.id+1))
        with self.assertRaises(ValueError):
            validate_scope(g.state, g.registry, forged)

    def test_resigned_snapshot_rejects_missing_or_changed_frozen_physical_proof(self):
        g = self.game((FLESH, KILL), (WATCH,), mode='wait')
        cid = self.manufacture(g)
        self.play(g, KILL, self.play(g, cid))
        original = g.snapshot()
        for alteration in ('missing', 'foreign', 'future', 'untyped'):
            bad = deepcopy(original)
            source = bad['state']['death_history'][0]['copy_source']
            if alteration == 'missing':
                bad['state']['death_history'][0]['copy_source'] = None
            elif alteration == 'foreign':
                source['origin']['card_id'] = FILL
            elif alteration == 'future':
                source['next_attachment_id'] = bad['state']['next_attachment_id']+1
            else:
                source['silenced'] = 1
            rehash(bad)
            with self.subTest(alteration=alteration), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, fixture('wait', 'reader'))

    def test_old_schema_is_rejected_and_bounced_copy_uses_ordinary_reset(self):
        g = self.game((FLESH, KILL, KILL, BOUNCE))
        cid = self.manufacture(g)
        self.play(g, KILL, self.play(g, cid))
        copied, = self.copies(g, cid)
        self.play(g, BOUNCE, copied.id)
        source = self.play(g, cid)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 3))
        self.play(g, KILL, source)
        new, = self.copies(g, cid)
        self.assertEqual((new.attack, new.health), (6, 3))
        bad = g.snapshot()
        bad['schema_version'] = 586
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, fixture())


if __name__ == '__main__':
    unittest.main()
