"""A real Librarian suffix reuses the accepted original death-copy program.

The current Mage diagnostic hand is supplied Bloodcraft, not a legal starting
deck or a claim about a complete formal generation/Assemble domain.
"""
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.assemble_dual_minion_play_followups import load_batch
from hs_sim.cards.assemble_source_exception_cards import THAW
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup, Scenario,
    SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, DamageKind,
    DeathrattleRepeatSpec, Rarity, TargetSpec)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from tools import card_batch as batch

BOOK, BASE, OTHER, COIN = 'TLC_226', 'CORE_EX1_096', 'CATA_483', 'GAME_005'
CID = AssembleRecipe(BASE, BOOK, 'bottom').card_id
REVEAL = 'JAIL_379'
CTX = GenerationContext('k519-librarian-reviewed-diagnostic-domain', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON)
P = 'fixture.librarian_death_copy.'
KILL, GROW, WOUND, ACTIVE, GIVE, MUTE = (
    P+s for s in ('kill', 'grow', 'wound', 'active', 'give', 'mute'))
WATCH, FAIL, FILL, REPEAT = (P+s for s in ('watch', 'fail', 'fill', 'repeat'))


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k519.'+mode
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        WOUND: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        ACTIVE: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        MUTE: lambda c: (Silence(c.target_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1,
            metadata=META, on_play=cid, targeting=TargetSpec(kinds=(CardType.MINION,))))

    def fail(c):
        raise ResolutionError('deliberate Librarian copy-notification failure')

    def watch(c):
        if mode not in ('wait', 'fail') or c.event is None:
            return ()
        target = c.state.entities[c.event.target_id]
        if target.card_id != CID or dict(c.event.data).get('copied_from') is None:
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, attack=0,
        health=20, metadata=META, triggers=(TriggerSpec('minion_summoned', WATCH),)))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=0, health=20, metadata=META))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, attack=0,
        health=20, metadata=META, deathrattle_repeats=(DeathrattleRepeatSpec(2),)))
    r.register_pool(PoolDefinition(POOL_ID, 'four-real-reviewed-faces-v1', CTX.target_id,
        CTX.mode, tuple(PoolMember(cid) for cid in ((BASE, BOOK, OTHER, REVEAL, 'TLC_429', 'CORE_EX1_110')
            if mode == 'thaw' else (BASE, BOOK, OTHER, REVEAL))), complete=True))
    return r


class LibrarianDeathCopyTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, extra=(), board=(), *, actor=1, mode='normal', seed=1):
        self.mode = mode
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_08',
            hand=(FLESH, *extra) if p == actor else (),
            board=board if p == actor else (), deck=(COIN,)*16,
            mana=50, max_mana=50, mana_cap=50) for p in (1, 2)),
            active_player=actor, seed=seed, generation_context=CTX), fixture(mode))

    def play(self, g, cid, target=None):
        return super().play(g, cid, target, player=g.state.active_player)

    def manufacture(self, g):
        self.play(g, FLESH)
        q = g.state.pending_choice
        option = next(o for o in q.options if o.card_id == CID)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return self.play(g, CID)

    def copies(self, g, actor=1):
        return [g.state.entities[i] for i in g.state.players[actor].board
            if g.state.entities[i].card_id == CID]

    def test_complete_original_faces_and_canonical_self_keep_original_draw_and_kindred(self):
        d = load_batch()
        row = next(x for x in d['existing_dependencies'] if x['record']['id'] == BOOK)
        self.assertEqual(batch.canonical(row['record']), row['record_sha256'])
        r = fixture()
        self.assertEqual(batch.canonical(asdict(r.card(BOOK))), row['definition_sha256'])
        for obs in (o for o in d['official_observations'] if o['card_id'] == BOOK):
            path = Path(obs['response_file'])
            self.assertEqual(batch.sha(path), obs['response_sha256'])
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([x for x in data['cards'] if x['id'] == row['record']['dbf_id']], [obs['face']])
            batch.check_face(row['record'], obs['face'], obs['locale'])
        self_face = asdict(r.card(AssembleRecipe(BOOK, BOOK, 'top').card_id))
        # Native Kindred self-assembly already uses its original condition wrapper.
        self.assertEqual(batch.canonical({k: v for k, v in self_face.items() if k not in ('id', 'on_play')}),
            batch.canonical({k: v for k, v in row['definition'].items() if k not in ('id', 'on_play')}))
        self.assertTrue(self_face['on_play'].startswith('assemble.condition:'))
        self.assertEqual(asdict(r.kindred_profiles[BOOK]), d['original_kindred_profiles'][BOOK])
        self.assertIn('deathrattle', r.assemble_templates[BOOK].suffix.allowed_timings)
        self.assertEqual(r.assemble_templates[BOOK].suffix.pending_timings, ())

    def test_actual_bloodcraft_two_players_natural_copy_uses_original_full_health_without_draw(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game((GROW, WOUND, KILL), actor=actor)
                eid = self.manufacture(g)
                self.assertEqual(g.state.players[actor].mana, 45)
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (4, 3))
                self.play(g, GROW, eid); self.play(g, WOUND, eid)
                self.assertEqual(g.state.entities[eid].damage, 1)
                draw_count = len(g.state.draw_history)
                self.play(g, KILL, eid)
                copies = self.copies(g, actor)
                self.assertEqual(len(copies), 1)
                self.assertNotEqual(copies[0].id, eid)
                self.assertEqual((copies[0].attack, copies[0].max_health, copies[0].damage), (6, 6, 0))
                self.assertEqual(g.state.players[actor].mana, 42)
                self.assertEqual(len(g.state.draw_history), draw_count)
                self.assertFalse(g.state.kindred_history)
                self.assertFalse(g.state.battlecry_history)
                self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
                self.assertEqual(len(g.state.death_history), 1)
                self.assertEqual(g.state.death_history[0].copy_source.origin.entity_id, eid)

    def test_active_deathrattle_preserves_live_damage_and_does_not_run_kindred_or_spell_draw(self):
        g = self.game((GROW, WOUND, ACTIVE))
        eid = self.manufacture(g)
        self.play(g, GROW, eid); self.play(g, WOUND, eid)
        draw_count = len(g.state.draw_history)
        self.play(g, ACTIVE, eid)
        copies = self.copies(g)
        self.assertEqual(len(copies), 2)
        self.assertEqual({(e.attack, e.max_health, e.damage) for e in copies}, {(6, 6, 1)})
        self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.kindred_history)
        self.assertEqual(len(g.state.draw_history), draw_count)

    def test_opposite_loot_half_draws_on_actual_outcast_play_and_again_on_death(self):
        cid = AssembleRecipe(BASE, 'BE_264', 'top').card_id
        self.mode = 'normal'
        g = Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=(cid, KILL), deck=(COIN,)*8,
                mana=10, max_mana=10),
            PlayerSetup('HERO_08', deck=(COIN,)*8)), seed=519), fixture())
        eid = self.play(g, cid)
        self.assertEqual(len(g.state.draw_history), 1)
        self.assertEqual(g.state.players[1].mana, 8)
        self.play(g, KILL, eid)
        self.assertEqual(len(g.state.draw_history), 2)
        self.assertFalse(g.state.kindred_history)
        self.assertFalse(g.state.battlecry_history)

    def test_actual_thaw_manufactures_spellcaster_on_play_copy_without_its_condition(self):
        cid = AssembleRecipe(BOOK, OTHER, 'bottom').card_id
        g = self.game((BOOK, THAW, KILL), mode='thaw', seed=6)
        self.play(g, BOOK)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, THAW)
        q = g.state.pending_choice
        option = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        eid = self.play(g, cid)
        copies = [g.state.entities[i] for i in g.state.players[1].board
            if g.state.entities[i].card_id == cid]
        self.assertEqual(len(copies), 2)
        self.assertEqual({(e.attack, e.max_health) for e in copies}, {(2, 2)})
        self.assertFalse(g.state.damage_history)
        before = len(g.state.draw_history)
        self.play(g, KILL, eid)
        self.assertEqual(len(g.state.draw_history), before+1)
        self.assertEqual(sum(g.state.entities[i].card_id == cid
            for i in g.state.players[1].board), 1)

    def test_successive_natural_deaths_each_keep_the_same_authored_suffix(self):
        g = self.game((KILL, KILL))
        original = self.manufacture(g)
        self.play(g, KILL, original)
        first = self.copies(g)[0].id
        self.play(g, KILL, first)
        second = self.copies(g)[0]
        self.assertEqual(len({original, first, second.id}), 3)
        self.assertEqual((second.attack, second.max_health, second.damage), (4, 3, 0))
        self.assertEqual(len(g.state.death_history), 2)
        self.assertFalse(g.state.kindred_history)
        self.assertFalse(g.state.draw_history)

    def test_repeat_plan_copies_the_one_original_death_twice_without_extra_paid_play(self):
        g = self.game((KILL,), board=(REPEAT,))
        eid = self.manufacture(g)
        plays = len(g.state.play_history)
        self.play(g, KILL, eid)
        self.assertEqual(len(self.copies(g)), 2)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertEqual(len(g.state.play_history), plays+1)
        self.assertEqual({e.owner for e in self.copies(g)}, {1})

    def test_waiting_restore_clone_replay_really_resume_and_bad_choice_is_atomic(self):
        g = self.game((KILL,), board=(WATCH,), mode='wait')
        eid = self.manufacture(g)
        self.play(g, KILL, eid)
        self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate Librarian'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        reader = fixture(self.mode, 'independent-reader')
        self.assertIsNot(reader, g.registry)
        legs = (g, Game.from_snapshot(json.loads(json.dumps(saved)), reader),
            g.clone(), replay(build_replay(g), reader))
        for other in legs:
            self.assertEqual(other.snapshot(), saved)
            self.choose(other)
            self.assertEqual(len(self.copies(other)), 1)
            self.assertFalse(other.state.kindred_history)
        self.assertTrue(all(other.snapshot() == g.snapshot() for other in legs))
        self.portable(g)

    def test_late_copy_notification_failure_rolls_back_original_death_payment_and_history(self):
        g = self.game((KILL,), board=(WATCH,), mode='fail')
        eid = self.manufacture(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate Librarian'):
            self.play(g, KILL, eid)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(g.state.entities[eid].zone, Zone.BOARD)
        self.assertFalse(g.state.death_history)

    def test_transferred_source_copies_for_actual_death_controller(self):
        g = self.game((GIVE, KILL))
        eid = self.manufacture(g)
        self.play(g, GIVE, eid)
        self.play(g, KILL, eid)
        self.assertFalse(self.copies(g, 1))
        copy = self.copies(g, 2)[0]
        self.assertEqual((copy.owner, copy.controller, copy.damage), (2, 2, 0))
        self.assertEqual(g.state.death_history[-1].controller, 2)

    def test_silence_removes_authored_copy_and_full_board_does_not_queue_later_copy(self):
        g = self.game((MUTE, KILL))
        eid = self.manufacture(g)
        self.play(g, MUTE, eid); self.play(g, KILL, eid)
        self.assertFalse(self.copies(g))
        g = self.game((ACTIVE, KILL), board=(FILL,)*6)
        eid = self.manufacture(g)
        self.play(g, ACTIVE, eid)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(len(self.copies(g)), 1)
        self.play(g, KILL, g.state.players[1].board[0])
        self.assertEqual(len(self.copies(g)), 1)


if __name__ == '__main__':
    unittest.main()
