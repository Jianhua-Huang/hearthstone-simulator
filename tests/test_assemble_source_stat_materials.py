"""Real source parameters, physical native spells, and explicit unknown death stats."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_source_stat_materials as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import FLESH, SHAPER, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    GrantKeyword, InvokeBehavior, RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword, SourceAttackSpellValue, SpellBaseDamageValue
from hs_sim.engine.native_spell_values import public_value
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.source_attack_spells import SourceAttackSpellProfile
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

EXPERIMENT, REDEEMER = cards.SOURCES
BREATH, DRAGON = cards.BREATH, cards.DRAGON
DRAIN, RUST, CLEANER, CURATOR, GOLEM = 'CORE_GIL_622', 'CORE_SW_072', 'CORE_REV_946', 'CORE_KAR_061', 'BE_861'
COIN = 'GAME_005'
P = 'k440.'
N, KILL, BUFF, HIT, ZERO, COPY, BASE_COPY, MORPH, SHUFFLE, RECAST, SHIELD, WATCH, FAIL = (
    P+k for k in ('n', 'kill', 'buff', 'hit', 'zero', 'copy', 'base_copy', 'morph',
        'shuffle', 'recast', 'shield', 'watch', 'fail'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CTX = GenerationContext('k440-reviewed-source-stat-explicit-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version += '.k440.'+mode
    r.register_card(CardDefinition(N, N, CardType.MINION, health=20, metadata=META))
    def fail(c): raise ResolutionError('K440 deliberate native material continuation failure')
    def watch(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.target_id].card_id != BREATH: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('go', 'Continue'),
            ChoiceOption('grow', 'Change original after capture', (Buff(c.event.source_id, 9, source_id=c.source_id),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))),
            c.source_id),)
    r.register_behavior(FAIL, fail); r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_added_to_hand', WATCH),)))
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        BUFF: lambda c: (Buff(c.target_id, 2, 3, source_id=c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        ZERO: lambda c: (Buff(c.target_id, -3, source_id=c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='current', source_id=c.source_id),),
        BASE_COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='base', source_id=c.source_id),),
        MORPH: lambda c: (Transform(c.target_id, N),),
        SHUFFLE: lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, Zone.DECK, position='top', source_id=c.source_id), Draw(c.player_id)),
        RECAST: lambda c: (RecastSpell(c.player_id, next(x.id for x in c.state.cast_history
            if x.card_id == BREATH), c.source_id, c.state.players[3-c.player_id].hero_id, 'explicit'),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        targeting = (TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,)) if cid in (COPY, BASE_COPY, SHUFFLE)
            else None if cid == RECAST else TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=targeting, metadata=META))
    domains = {'experiment_offer': (EXPERIMENT, DRAIN, RUST),
        'redeemer_offer': (REDEEMER, CLEANER, CURATOR), 'pending_offer': (GOLEM, DRAIN, REDEEMER)}
    if mode in domains:
        r.register_pool(PoolDefinition(POOL_ID, 'k440-complete-three-member-explicit-source-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in domains[mode]), complete=True))
    if mode == 'no_source_profile': r._source_attack_spell_profiles.clear()
    if mode == 'missing_dragon': del r._cards[DRAGON]
    r.validate(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class AssembleSourceStatTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='normal'):
        hero = 'HERO_04' if mode in ('redeemer_offer', 'pending_offer') else 'HERO_11'
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board,
            deck=(COIN,)*24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', deck=(COIN,)*24, mana=50, max_mana=50, mana_cap=50)),
            seed=1, generation_context=CTX), fixture(mode))

    def ids(self, g, cid, zone='hand'):
        return [i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid]

    def play(self, g, cid, target=None):
        source = self.ids(g, cid)[0]; g.apply(PlayCard(1, source, target)); return source

    def end(self, g): g.apply(EndTurn(g.state.active_player))

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def value(self, g, eid=None):
        e = g.state.entities[eid or self.ids(g, BREATH)[0]]
        return next(a.spell_base_value for a in e.abilities if a.kind == 'spell_base_value')

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        self.assertEqual(g.snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for field in ('next_entity_id', 'native_spell_value', 'source_attack_spell_profiles', 'deathrattle_id'):
                self.assertNotIn('"'+field+'"', public)
        return other

    def test_a_four_complete_originals_primary_faces_and_true_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES+(BREATH, DRAGON)); self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid in cards.SOURCES:
            old = asdict(r.card(cid)); new = asdict(r.card(recipe(cid))); new['id'] = cid
            self.assertEqual(new, old); self.assertEqual(recipe_options(r, cid, cid), ())
        self.assertEqual(canonical_digest(asdict(r.spell_value_profiles[BREATH])), d['native_damage_profile_sha256'])

    def test_b_raw_and_self_experiment_use_real_death_record_and_native_paid_spell(self):
        for cid in (EXPERIMENT, recipe(EXPERIMENT)):
            g = self.game((cid, BUFF, KILL)); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 48)
            self.play(g, BUFF, source); self.play(g, KILL, source)
            value = self.value(g); self.assertIs(type(value), SpellBaseDamageValue)
            self.assertEqual(value.amount, 5); self.assertEqual(len(g.state.deathrattle_history), 1)
            before = g.state.players[1].mana; self.play(g, BREATH, g.state.players[2].hero_id)
            self.assertEqual(g.state.players[1].mana, before-2); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)

    def test_c_changed_battlecry_prefix_uses_frozen_source_value_without_fake_death(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid,)); source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, 48); self.assertIsNone(g.registry.card(cid).deathrattle)
        v = self.value(g); self.assertIs(type(v), SourceAttackSpellValue)
        self.assertEqual((v.amount, v.source.entity_id, v.source.card_id, v.source.controller), (3, source, cid, 1))
        self.assertEqual(g.state.deathrattle_history, [])

    def test_d_experiment_prefix_replaces_its_body_without_generating_old_breath(self):
        cid = recipe(EXPERIMENT, DRAIN); g = self.game((cid, KILL)); source = self.play(g, cid)
        self.assertEqual(self.ids(g, BREATH), []); self.play(g, KILL, source)
        self.assertEqual(self.ids(g, BREATH), []); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_e_borrowed_attack_body_runs_at_native_end_with_actual_source_stats(self):
        cid = recipe(REDEEMER, EXPERIMENT); g = self.game((BUFF,), (cid,)); source = self.ids(g, cid, 'board')[0]
        self.play(g, BUFF, source); self.end(g)
        self.assertIs(type(self.value(g)), SourceAttackSpellValue); self.assertEqual(self.value(g).amount, 5)
        self.assertEqual(self.ids(g, DRAGON, 'board'), []); self.portable(g)

    def test_f_raw_and_self_redeemer_use_native_remaining_health_without_copying_abilities(self):
        for cid in (REDEEMER, recipe(REDEEMER)):
            g = self.game((cid, BUFF, HIT, SHIELD)); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 45)
            for helper in (BUFF, HIT, SHIELD): self.play(g, helper, source)
            self.end(g); dragon = g.state.entities[self.ids(g, DRAGON, 'board')[0]]
            self.assertEqual((dragon.attack, dragon.health, dragon.max_health), (5, 5, 5))
            self.assertNotIn(Keyword.DIVINE_SHIELD, dragon.keywords); self.assertEqual(dragon.card_id, DRAGON)
            self.assertEqual(g.registry.card(DRAGON).triggers, ())

    def test_g_borrowed_dragon_body_uses_primary_battlecry_stats_and_no_old_damage(self):
        cid = recipe(DRAIN, REDEEMER); g = self.game((cid,)); self.play(g, cid)
        dragon = g.state.entities[self.ids(g, DRAGON, 'board')[0]]
        self.assertEqual((dragon.attack, dragon.health), (3, 3)); self.assertEqual(g.state.players[1].mana, 46)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_h_keep_redeemer_prefix_replace_body_does_not_keep_original_dragon(self):
        cid = recipe(REDEEMER, DRAIN); g = self.game((cid,)); self.play(g, cid); self.end(g)
        self.assertEqual(self.ids(g, DRAGON, 'board'), [])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_i_creation_wait_freezes_before_later_growth_and_failed_resume_rolls_back(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid,), (WATCH,)); source = self.play(g, cid)
        self.assertEqual(self.value(g).amount, 3); reader = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.pick(g, 'grow'); self.pick(reader, 'grow'); self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(g.state.entities[source].attack, 12); self.assertEqual(self.value(g).amount, 3)
        self.play(g, BREATH, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27); self.portable(g)

    def test_j_current_spell_copy_keeps_parameter_and_reallocates_attachment_after_source_transform(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid, COPY, MORPH)); source = self.play(g, cid)
        first = self.ids(g, BREATH)[0]; self.play(g, COPY, first); spells = self.ids(g, BREATH)
        values = [self.value(g, eid) for eid in spells]; self.assertEqual(values[0], values[1])
        attachments = [next(a.id for a in g.state.entities[eid].abilities if a.kind=='spell_base_value') for eid in spells]
        self.assertEqual(len(set(attachments)), 2); self.play(g, MORPH, source)
        for _ in spells: self.play(g, BREATH, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24); self.portable(g)

    def test_k_same_physical_spell_survives_shuffle_and_draw(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid, SHUFFLE)); self.play(g, cid)
        spell = self.ids(g, BREATH)[0]; value = self.value(g); self.play(g, SHUFFLE, spell)
        self.assertEqual(self.ids(g, BREATH), [spell]); self.assertEqual(self.value(g), value)
        self.play(g, BREATH, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_l_base_copy_remains_explicitly_unbound_and_rejects_whole_payment(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid, BASE_COPY)); self.play(g, cid)
        original = self.ids(g, BREATH)[0]; self.play(g, BASE_COPY, original)
        unbound = next(eid for eid in self.ids(g, BREATH) if eid != original); saved = g.snapshot()
        with self.assertRaises(ValueError): g.apply(PlayCard(1, unbound, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), saved); self.assertEqual(public_value(g.state.entities[unbound]), None)

    def test_m_historical_cast_reuses_original_source_value_after_source_change(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid, MORPH, RECAST)); source = self.play(g, cid)
        self.play(g, BREATH, g.state.players[2].hero_id); self.play(g, MORPH, source); self.play(g, RECAST)
        casts = [x for x in g.state.cast_history if x.card_id == BREATH]
        self.assertEqual(len(casts), 2); self.assertEqual([x.native_spell_value.spell_base_value.amount for x in casts], [3, 3])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24); self.portable(g)

    def test_n_zero_attack_is_a_bound_zero_value_and_spell_still_pays_native_cost(self):
        cid = recipe(REDEEMER, EXPERIMENT); g = self.game((ZERO,), (cid,))
        self.play(g, ZERO, self.ids(g, cid, 'board')[0]); self.end(g); self.end(g)
        self.assertEqual(self.value(g).amount, 0); before = g.state.players[1].mana
        self.play(g, BREATH, g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, before-2); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_o_missing_source_profile_or_actual_dragon_dependency_rolls_back(self):
        for cid,mode in ((recipe(EXPERIMENT, DRAIN, 'top'), 'no_source_profile'),
                (recipe(DRAIN, REDEEMER), 'missing_dragon')):
            g = self.game((cid,), mode=mode); saved = g.snapshot()
            with self.assertRaises(ValueError): self.play(g, cid)
            self.assertEqual(g.snapshot(), saved)

    def test_p_local_policy_excludes_only_unreviewed_redeemer_death_result(self):
        with self.assertRaises(ValueError): fixture().card(recipe(GOLEM, REDEEMER))
        g = self.game((FLESH,), mode='pending_offer'); self.play(g, FLESH)
        options = {o.card_id for o in g.state.pending_choice.options}
        self.assertNotIn(recipe(GOLEM, REDEEMER), options)
        self.assertIn(recipe(GOLEM, REDEEMER, 'top'), options)
        self.portable(g, 'pending_offer')

    def test_q_real_flesh_offer_keeps_primary_price_and_native_buffed_attack_spell(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((FLESH,), mode='experiment_offer')
        entry = self.play(g, FLESH); self.portable(g, 'experiment_offer'); q = g.state.pending_choice
        self.assertIn(cid, [o.card_id for o in q.options]); self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        source = self.play(g, cid); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (5, 3))
        self.assertEqual(self.value(g).amount, 5); self.assertEqual(g.state.entities[entry].zone, Zone.GRAVEYARD)
        self.play(g, BREATH, g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, 43); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)
        self.portable(g, 'experiment_offer')

    def test_r_real_shaper_offer_uses_selected_battlecry_and_plain_native_dragon(self):
        cid = recipe(REDEEMER, CLEANER, 'top'); g = self.game((SHAPER,), mode='redeemer_offer')
        entry = self.play(g, SHAPER); self.portable(g, 'redeemer_offer'); q = g.state.pending_choice
        self.assertIn(cid, [o.card_id for o in q.options]); self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        source = self.play(g, cid); dragon = g.state.entities[self.ids(g, DRAGON, 'board')[0]]
        self.assertEqual((dragon.attack, dragon.health), (3, 3)); self.assertEqual(g.state.players[1].mana, 43)
        self.assertEqual(g.state.entities[entry].zone, Zone.BOARD); self.assertEqual(g.registry.card(cid).triggers, ())
        self.assertNotIn(Keyword.TAUNT, g.state.entities[source].keywords); self.portable(g, 'redeemer_offer')

    def test_s_source_profile_is_unique_readonly_fingerprinted_and_frozen(self):
        r = fixture.__wrapped__(); profile = r.source_attack_spell_profiles[BREATH]; before = r.fingerprint()
        with self.assertRaises(TypeError): r.source_attack_spell_profiles[BREATH] = profile
        with self.assertRaises(ValueError): r.register_source_attack_spell_profile(profile)
        with self.assertRaises(ValueError): r.register_source_attack_spell_profile(replace(profile, source_card_id=REDEEMER))
        with self.assertRaises(ValueError): r.register_source_attack_spell_profile(replace(profile, behavior_id='missing.k440'))
        del r._source_attack_spell_profiles[BREATH]; self.assertNotEqual(r.fingerprint(), before)
        r.register_source_attack_spell_profile(profile); self.assertEqual(r.fingerprint(), before)
        r.freeze()
        with self.assertRaises(ValueError): r.register_source_attack_spell_profile(profile)

    def test_t_source_value_roundtrip_rejects_foreign_allocation_and_incomplete_material(self):
        cid = recipe(EXPERIMENT, DRAIN, 'top'); g = self.game((cid,)); self.play(g, cid); self.portable(g)
        saved = g.snapshot(); self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        spell = str(self.ids(g, BREATH)[0])
        def value_of(s):
            entities = s['state']['entities']; entity = entities[spell] if isinstance(entities, dict) else next(x for x in entities if x['id']==int(spell))
            return next(a for a in entity['abilities'] if a['kind']=='spell_base_value')['spell_base_value']
        for mutate in (lambda v:v.update(turn=999999), lambda v:v['source'].update(next_entity_id=999999),
                lambda v:v['source'].update(kind='hero'), lambda v:v.update(unreviewed=1)):
            bad = json.loads(json.dumps(saved)); mutate(value_of(bad)); rehash(bad)
            with self.assertRaises((ValueError, SnapshotError)): Game.from_snapshot(bad, fixture('normal', 'reader'))


if __name__ == '__main__': unittest.main()
