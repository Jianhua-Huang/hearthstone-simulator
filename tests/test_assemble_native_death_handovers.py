"""Two original death bodies, genuine death operands and actual Assemble offers."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_native_death_handovers as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, validate_template
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, LOOT, N

RATTLER, SERVANT = cards.SOURCES
FIRE, BEETLE, IRON, AUCTION = 'CORE_UNG_809', 'CORE_LOOT_413', 'BE_996', 'JAIL_718'
P = 'k437.'
KILL, GROW, MUTE, GIVE, COPY, BASE_COPY, PREY, POWER, HWATCH, BWATCH, FAIL = (
    P + key for key in ('kill', 'grow', 'mute', 'give', 'copy', 'base_copy',
                       'prey', 'power', 'health_watch', 'buff_watch', 'fail'))
CTX = GenerationContext('k437-complete-original-death-subject-domain', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k437.' + mode
    r.register_card(CardDefinition(PREY, PREY, CardType.MINION, attack=9, health=1, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=8, spell_damage=5, metadata=META))
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, attack=5, source_id=c.source_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        BASE_COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('K437 deliberate native death continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or not (source.card_id in cards.SOURCES or source.card_id.startswith('assemble:')):
            return ()
        depart = (ChoiceOption('depart', 'Source leaves', (Destroy(source.id, c.source_id),)),) if source.zone == Zone.BOARD else ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id))), *depart), c.source_id),)
    for cid, event in ((HWATCH, 'health_resolved'), (BWATCH, 'stats_changed')):
        r.register_behavior(cid, watch)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, cid),)))
    if mode in ('warlock', 'demon_hunter'):
        primary = SERVANT if mode == 'warlock' else RATTLER
        r.register_pool(PoolDefinition(POOL_ID, 'k437-native-low-primary-two-neutral-five-nine-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (primary, IRON, AUCTION)), complete=True))
    r.validate(); return r


class AssembleNativeDeathTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal'):
        hero = 'HERO_07' if mode == 'warlock' else 'HERO_10'
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', board=enemy, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=437, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='board', player=1):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        source = self.eid(g, cid, 'hand'); g.apply(PlayCard(1, source, target)); return source

    def attack(self, g, player=1):
        return sum(g.state.entities[i].attack for i in g.state.players[player].board)

    def count(self, g, cid=COIN, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None: self.pick(g)

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'primary_candidates', 'MinionReference'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_complete_rows_faces_exact_native_bodies_and_true_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 2); self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        before = r.fingerprint()
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual(r.assemble_templates[cid].suffix.behavior_id, old.deathrattle)
            self.assertEqual((new.cost, new.attack, new.health, new.keywords, new.metadata),
                (old.cost, old.attack, old.health, old.keywords, old.metadata))
            self.assertEqual(recipe_options(r, cid, cid), ())
        self.assertEqual(r.fingerprint(), before)

    def test_b_original_and_self_rattler_pay_once_damage_enemy_minions_one_without_spell_bonus(self):
        for cid in (RATTLER, recipe(RATTLER)):
            g = self.game((cid, KILL), (N, POWER), (N, N)); mana = g.state.players[1].mana
            source = self.play(g, cid); self.assertEqual(g.state.players[1].mana, mana-3)
            self.assertIn(Keyword.RUSH, g.state.entities[source].keywords); self.play(g, KILL, source)
            self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [11, 11])
            self.assertEqual(g.state.entities[self.eid(g, N)].health, 12)
            self.assertEqual([g.state.entities[p.hero_id].health for p in g.state.players.values()], [30, 30])

    def test_c_original_and_self_servant_grant_frozen_actual_death_attack_not_reset_printed_attack(self):
        for cid in (SERVANT, recipe(SERVANT)):
            g = self.game((cid, GROW, KILL), (N,)); mana = g.state.players[1].mana
            source = self.play(g, cid); self.assertEqual(g.state.players[1].mana, mana-1)
            self.play(g, GROW, source); self.play(g, KILL, source)
            self.assertEqual(g.state.death_history[-1].attack, 7)
            self.assertEqual(g.state.entities[self.eid(g, N)].attack, 8)

    def test_d_empty_friendly_set_is_noop_without_random_draw_for_original_and_self(self):
        for cid in (SERVANT, recipe(SERVANT)):
            g = self.game((cid, KILL)); source = self.play(g, cid); rng = g.snapshot()['rng_state']
            self.play(g, KILL, source); self.assertEqual(g.snapshot()['rng_state'], rng)
            self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.players[1].board)

    def test_e_living_battlecry_servant_body_uses_primary_attack_and_can_select_itself(self):
        cid = recipe(FIRE, SERVANT); g = self.game((cid,)); source = self.play(g, cid)
        self.assertEqual(g.state.entities[source].attack, 2)
        self.assertIsNone(g.registry.card(cid).deathrattle); self.assertEqual(self.count(g), 0)

    def test_f_borrowed_rattler_battlecry_damages_once_without_old_rush_or_deathrattle(self):
        cid = recipe(FIRE, RATTLER); g = self.game((cid,), enemy=(N,)); self.play(g, cid)
        self.assertEqual(g.state.entities[self.eid(g, N, player=2)].health, 11)
        self.assertNotIn(Keyword.RUSH, g.registry.card(cid).keywords)
        self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_g_rattler_death_prefix_keeps_rush_but_only_runs_selected_loot_draw(self):
        cid = recipe(RATTLER, LOOT); g = self.game((cid, KILL), enemy=(N,)); source = self.play(g, cid)
        self.assertIn(Keyword.RUSH, g.state.entities[source].keywords); self.play(g, KILL, source)
        self.assertEqual(self.count(g), 1); self.assertEqual(g.state.entities[self.eid(g, N, player=2)].health, 12)

    def test_h_servant_death_prefix_selected_armor_does_not_keep_old_attack_grant(self):
        cid = recipe(SERVANT, BEETLE); g = self.game((cid, KILL), (N,)); source = self.play(g, cid)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertEqual(g.state.entities[self.eid(g, N)].attack, 1)

    def test_i_rattler_enemy_deaths_share_one_real_damage_batch_and_leave_heroes_untouched(self):
        cid = recipe(FIRE, RATTLER); g = self.game((cid,), enemy=(PREY, PREY)); self.play(g, cid)
        deaths = [d for d in g.state.death_history if d.card_id == PREY]
        self.assertEqual(len(deaths), 2); self.assertEqual(len({d.batch for d in deaths}), 1)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_j_random_physical_target_and_frozen_attack_wait_restore_and_failed_resume(self):
        cid = recipe(SERVANT); g = self.game((cid, GROW, KILL), (N, N, BWATCH))
        source = self.play(g, cid); self.play(g, GROW, source)
        before = self.attack(g)-7; self.play(g, KILL, source)
        reader = self.portable(g); saved = g.snapshot(); rng = saved['rng_state']
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.pick(g); self.pick(reader)
        self.assertEqual(g.snapshot(), reader.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(self.attack(g), before+7); self.assertIsNone(g.state.pending_choice)

    def test_k_transferred_original_death_bodies_use_current_controller_not_original_owner(self):
        for cid in (recipe(RATTLER), recipe(SERVANT)):
            g = self.game((GIVE, KILL), (cid, N), (N,)); source = self.eid(g, cid)
            self.play(g, GIVE, source); self.play(g, KILL, source)
            own = g.state.entities[self.eid(g, N)]; other = g.state.entities[self.eid(g, N, player=2)]
            self.assertEqual((own.health, other.health), (11, 12) if cid == recipe(RATTLER) else (12, 12))
            self.assertEqual((own.attack, other.attack), (1, 3) if cid == recipe(SERVANT) else (1, 1))

    def test_l_silenced_current_copy_stays_silent_base_copy_keeps_new_printed_death_body(self):
        cid = recipe(SERVANT, BEETLE); g = self.game((MUTE, COPY, BASE_COPY, KILL), (cid,))
        source = self.eid(g, cid); self.play(g, MUTE, source)
        old = set(g.state.players[1].board); self.play(g, COPY, source)
        current = (set(g.state.players[1].board)-old).pop(); self.assertTrue(g.state.entities[current].silenced)
        old = set(g.state.players[1].board); self.play(g, BASE_COPY, source)
        base = (set(g.state.players[1].board)-old).pop(); self.assertFalse(g.state.entities[base].silenced)
        self.play(g, KILL, base); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)

    def test_m_real_mismatch_two_current_class_domains_keep_entry_and_ignore_enemy_death_attack(self):
        for primary, mode in ((SERVANT, 'warlock'), (RATTLER, 'demon_hunter')):
            cid = recipe(primary, IRON, 'top'); g = self.game((MISMATCH, KILL), enemy=(PREY, N), mode=mode)
            entry = self.play(g, MISMATCH)
            if primary == SERVANT: self.portable(g, mode)
            q = g.state.pending_choice; self.pick(g, next(o.id for o in q.options if o.card_id == cid))
            mana = g.state.players[1].mana; source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, mana-g.registry.card(primary).cost)
            self.assertIn(entry, g.state.players[1].board); self.assertNotIn(Keyword.RUSH, g.state.entities[source].keywords)
            old_attack = self.attack(g); self.play(g, KILL, self.eid(g, PREY, player=2))
            self.assertEqual(g.state.death_history[-1].attack, 9)
            if primary == SERVANT: self.assertEqual(self.attack(g), old_attack+2)
            else: self.assertEqual(g.state.entities[self.eid(g, N, player=2)].health, 11)
            if primary == SERVANT: self.portable(g, mode)

    def test_n_damage_inner_wait_survives_source_departure_without_retargeting_or_second_payment(self):
        cid = recipe(FIRE, RATTLER); g = self.game((cid,), (HWATCH,), (N, N))
        source = self.play(g, cid); reader = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.pick(g, 'depart'); self.pick(reader, 'depart')
        self.drain(g); self.drain(reader); self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [11, 11])
        self.assertEqual(g.state.players[1].mana, 49)

    def test_o_full_original_drift_and_unreviewed_body_are_rejected_without_registry_mutation(self):
        r = fixture(); t = r.assemble_templates[SERVANT]
        with self.assertRaises(ValueError): validate_template(r, replace(t, suffix=replace(t.suffix, behavior_id='unknown.k437')))
        broken = fixture.__wrapped__(); broken._cards[SERVANT] = replace(broken.card(SERVANT), attack=3)
        with self.assertRaises(TargetValidationError): cards.register_assemble_native_death_handovers(broken)
        before = r.fingerprint(); self.assertEqual(recipe_options(r, RATTLER, RATTLER), ())
        self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
