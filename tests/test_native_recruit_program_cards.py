"""Actual Silver Hand sources/consumers and the shared controlled-card scope."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_recruit_program_cards import (OFFICER, RESCUER, REST,
    BLADE, TEAMWORK, ROOTS, RECRUIT, PREFIX, load_batch, register_native_recruit_program_cards)
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    Damage, Destroy, EquipWeapon, GainArmor, GrantKeyword, RandomDamage, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import (DamageKind, LimitedTriggerSpec, PlayerAuraSpec,
    PlayerEffectSpec, SpellSchool)
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

P = 'k189.'
HERO, FILL = P+'hero', P+'filler'


@lru_cache(maxsize=1)
def original_recruit():
    return build_registry().card(RECRUIT)


@lru_cache(maxsize=None)
def registry(mode=None):
    r = Registry('k189-controlled-recruits-'+str(mode))
    r.register_card(original_recruit())
    register_native_recruit_program_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=40))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=1, health=20))
    r.register_player_effect(PlayerEffectSpec(P+'old', P+'old', auras=(PlayerAuraSpec(1, 1, (RECRUIT,)),)))
    bodies = dict(
        hit=lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT),),
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        shield=lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        take=lambda c: (ChangeControl(c.target_id, 2),),
        bounce=lambda c: (ReturnToHand(c.target_id),),
        dormant=lambda c: (MakeDormant(c.target_id, 2, c.source_id),),
        transform=lambda c: (Transform(c.target_id, FILL),),
        buff=lambda c: (Buff(c.target_id, 2, 2, c.source_id),),
        old=lambda c: (AddPlayerEffect(c.player_id, P+'old', c.source_id),),
        create=lambda c: (AddToHand(c.player_id, RECRUIT, c.source_id),),
        copy=lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, source_id=c.source_id),),
        base=lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='base', source_id=c.source_id),),
        other_copy=lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), 2, source_id=c.source_id),),
    )
    for name, fn in bodies.items():
        targeted = name not in ('old', 'create')
        zones = (Zone.HAND,) if name in ('copy', 'base', 'other_copy') else (Zone.BOARD,)
        kwargs = dict(targeting=TargetSpec(zones=zones, kinds=(CardType.MINION,))) if targeted else {}
        r.register_behavior(P+name, fn)
        r.register_card(CardDefinition(P+name, P+name, CardType.SPELL, on_play=P+name, **kwargs))
    if mode:
        event = 'card_created' if mode == 'created' else 'minion_summoned' if mode == 'summoned' else 'player_effect_added'
        def eligible(c):
            return (c.event.player_id == c.player_id and (event == 'player_effect_added' or
                c.event.target_id is not None and c.state.entities[c.event.target_id].card_id == RECRUIT))
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail after random delivery', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), EquipWeapon(1, FILL)))]
            receipt = ()
            if mode == 'created':
                target = c.state.entities[c.event.target_id]
                receipt = (GainArmor(c.player_id, target.attack*100+target.max_health),)
            return (*receipt, RequestChoice(c.player_id, tuple(options), c.source_id))
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    return r


class NativeRecruitProgramTests(unittest.TestCase):
    def game(self, hand=(BLADE,), board=(), deck=(FILL,)*6, enemy=(), mode=None):
        self.mode = mode
        if mode: board = (*board, P+'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=deck, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, board=enemy, deck=(FILL,)*6, mana=30, max_mana=30, mana_cap=30)), seed=189), registry(mode))

    def play(self, g, cid=BLADE, target=None):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, i, target))
        return i

    def first(self, g, cid, zone='board', p=1):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def recruits(self, g, zone='board', p=1):
        return [g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == RECRUIT]

    def stats(self, g, zone='board', p=1):
        return [(e.attack, e.max_health) for e in self.recruits(g, zone, p)]

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); reader = registry.__wrapped__(self.mode)
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(deepcopy(s), reader)
        self.assertEqual(other.snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), s)
        return other

    def test_complete_five_original_faces_and_existing_recruit_pin(self):
        d = load_batch(); r = registry(); self.assertEqual(len(d['official_observations']), 10)
        self.assertEqual(len(d['recipient_ids']), 9)
        for row in d['cards']:
            raw = row['record']; card = r.card(raw['id'])
            self.assertEqual(card.metadata, metadata_from_record(raw))
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            self.assertEqual(card.cost, raw['cost'])
        self.assertEqual((r.card(OFFICER).attack, r.card(OFFICER).health), (2, 1))
        self.assertEqual((r.card(RESCUER).attack, r.card(RESCUER).health), (3, 1))
        self.assertEqual((r.card(BLADE).attack, r.card(BLADE).durability), (3, 2))
        self.assertEqual(r.card(REST).spell_school, SpellSchool.HOLY)
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_real_weapon_battlecry_updates_only_owned_recruit_cards_in_all_live_zones(self):
        g = self.game((BLADE, RECRUIT), board=(RECRUIT, FILL), deck=(RECRUIT, FILL), enemy=(RECRUIT,))
        self.play(g)
        for zone in ('board', 'hand', 'deck'): self.assertEqual(self.stats(g, zone), [(2, 2)])
        self.assertEqual(self.stats(g, p=2), [(1, 1)])
        self.assertEqual(g.state.entities[self.first(g, FILL)].attack, 1)
        self.assertEqual((g.state.players[1].mana, len(g.state.players[1].player_effects)), (25, 1))

    def test_existing_active_board_player_aura_keeps_its_original_scope(self):
        g = self.game((P+'old', RECRUIT), board=(RECRUIT,), deck=(RECRUIT,)); self.play(g, P+'old')
        self.assertEqual(self.stats(g), [(2, 2)])
        self.assertEqual(self.stats(g, 'hand'), [(1, 1)])
        self.assertEqual(self.stats(g, 'deck'), [(1, 1)])

    def test_two_actual_weapon_battlecries_stack_and_outlive_replaced_weapon(self):
        g = self.game((BLADE, BLADE), board=(RECRUIT,)); first = self.play(g); self.play(g)
        self.assertEqual(g.state.entities[first].zone, Zone.GRAVEYARD)
        self.assertEqual(self.stats(g), [(3, 3)])
        self.assertEqual(len(g.state.players[1].player_effects), 2)

    def test_officer_has_rush_and_actual_death_grants_persistent_attack(self):
        g = self.game((OFFICER, P+'kill', TEAMWORK)); source = self.play(g, OFFICER)
        self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)
        self.play(g, P+'kill', source); self.play(g, TEAMWORK)
        self.assertEqual(self.stats(g), [(2, 1)]*4)
        self.assertEqual(self.stats(g, 'hand'), [(2, 1)]*4)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_officer_silence_removes_death_upgrade(self):
        g = self.game((P+'silence', P+'kill'), board=(OFFICER, RECRUIT)); source = self.first(g, OFFICER)
        self.play(g, P+'silence', source); self.play(g, P+'kill', source)
        self.assertEqual(g.state.players[1].player_effects, [])
        self.assertEqual(self.stats(g), [(1, 1)])

    def test_stolen_officer_death_rewards_actual_controller(self):
        g = self.game((P+'take', P+'kill'), board=(OFFICER, RECRUIT), enemy=(RECRUIT,))
        source = self.first(g, OFFICER); self.play(g, P+'take', source); self.play(g, P+'kill', source)
        self.assertEqual(self.stats(g), [(1, 1)])
        self.assertEqual(self.stats(g, p=2), [(2, 1)])

    def test_rescuer_only_its_actual_shield_loss_adds_one_health_program(self):
        g = self.game((P+'shield', P+'hit', P+'hit'), board=(RESCUER, RECRUIT)); recruit = self.first(g, RECRUIT)
        self.play(g, P+'shield', recruit); self.play(g, P+'hit', recruit)
        self.assertEqual(g.state.players[1].player_effects, [])
        self.play(g, P+'hit', self.first(g, RESCUER))
        self.assertEqual(self.stats(g), [(1, 2)])
        self.assertEqual(len(g.state.players[1].player_effects), 1)

    def test_rescuer_can_reward_each_new_actual_shield_loss(self):
        g = self.game((P+'hit', P+'shield', P+'hit'), board=(RESCUER, RECRUIT)); source = self.first(g, RESCUER)
        self.play(g, P+'hit', source); self.play(g, P+'shield', source); self.play(g, P+'hit', source)
        self.assertEqual(self.stats(g), [(1, 3)])
        self.assertEqual(len(g.state.players[1].player_effects), 2)

    def test_rescuer_opponent_source_and_silenced_source_do_not_reward_wrong_player(self):
        g = self.game((P+'hit',), board=(RECRUIT,), enemy=(RESCUER, RECRUIT))
        self.play(g, P+'hit', self.first(g, RESCUER, p=2))
        self.assertEqual(self.stats(g), [(1, 1)])
        self.assertEqual(self.stats(g, p=2), [(1, 2)])
        g = self.game((P+'silence',), board=(RESCUER, RECRUIT)); self.play(g, P+'silence', self.first(g, RESCUER))
        self.assertEqual(g.state.players[1].player_effects, [])

    def test_rest_summons_two_current_upgraded_recruits_with_removable_shield(self):
        g = self.game((BLADE, REST, P+'silence')); self.play(g); self.play(g, REST)
        self.assertEqual(self.stats(g), [(2, 2)]*2)
        self.assertTrue(all(Keyword.DIVINE_SHIELD in e.keywords for e in self.recruits(g)))
        first = self.first(g, RECRUIT); self.play(g, P+'silence', first)
        self.assertEqual((g.state.entities[first].attack, g.state.entities[first].max_health), (2, 2))
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[first].keywords)

    def test_teamwork_summons_four_and_gets_four_fresh_current_stat_cards(self):
        g = self.game((BLADE, TEAMWORK)); self.play(g); self.play(g, TEAMWORK)
        self.assertEqual(self.stats(g), [(2, 2)]*4)
        self.assertEqual(self.stats(g, 'hand'), [(2, 2)]*4)
        self.assertEqual(len({e.id for e in self.recruits(g)+self.recruits(g, 'hand')}), 8)
        self.assertTrue(all(Keyword.DIVINE_SHIELD not in e.keywords for e in self.recruits(g)))

    def test_full_board_does_not_prevent_four_hand_deliveries(self):
        g = self.game((TEAMWORK,), board=(RECRUIT,)*7); self.play(g, TEAMWORK)
        self.assertEqual(len(self.recruits(g)), 7)
        self.assertEqual(self.stats(g, 'hand'), [(1, 1)]*4)

    def test_full_hand_burn_keeps_all_four_requested_creations(self):
        g = self.game((TEAMWORK,)+(FILL,)*9); self.play(g, TEAMWORK)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(len(self.recruits(g, 'hand')), 1)
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id == RECRUIT and e.zone == Zone.GRAVEYARD]), 3)

    def test_created_card_observer_sees_upgraded_stats_and_wait_restores_whole_tail(self):
        g = self.game((BLADE, TEAMWORK), mode='created'); self.play(g); self.play(g, TEAMWORK)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.stats(g, 'hand'), [(2, 2)])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 202)
        # The listener's frozen context must already contain the contribution.
        self.assertEqual([(g.state.entities[i].attack, g.state.entities[i].max_health) for i in g.state.players[1].hand], [(2, 2)])
        other = self.portable(g)
        for x in (g, other): self.choose(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.stats(g, 'hand'), [(2, 2)]*4)

    def test_summon_wait_resume_uses_original_remaining_count_without_duplicates(self):
        g = self.game((BLADE, TEAMWORK), mode='summoned'); self.play(g); self.play(g, TEAMWORK)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.recruits(g)), 1)
        other = self.portable(g)
        for x in (g, other): self.choose(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.stats(g), [(2, 2)]*4)

    def test_waiting_failure_rolls_back_rng_health_and_original_deliveries(self):
        g = self.game((BLADE, TEAMWORK), mode='created'); self.play(g); self.play(g, TEAMWORK); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.assertEqual(len(self.recruits(g, 'hand')), 4)

    def test_upgrade_wait_already_has_all_zones_and_does_not_repeat_program(self):
        g = self.game((BLADE, RECRUIT), board=(RECRUIT,), deck=(RECRUIT,), mode='added'); self.play(g)
        self.assertEqual(self.stats(g, 'hand'), [(2, 2)])
        other = self.portable(g)
        for x in (g, other): self.choose(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.players[1].player_effects), 1)

    def test_control_transfer_and_transform_follow_current_identity(self):
        g = self.game((BLADE, P+'take'), board=(RECRUIT,)); self.play(g); recruit = self.first(g, RECRUIT)
        self.play(g, P+'take', recruit); self.assertEqual(self.stats(g, p=2), [(1, 1)])
        g = self.game((BLADE, P+'transform'), board=(RECRUIT,)); self.play(g); recruit = self.first(g, RECRUIT)
        self.play(g, P+'transform', recruit)
        self.assertEqual((g.state.entities[recruit].attack, g.state.entities[recruit].max_health), (1, 20))

    def test_bounce_and_replay_do_not_bake_or_duplicate_global_stats(self):
        g = self.game((BLADE, P+'bounce'), board=(RECRUIT,)); self.play(g); recruit = self.first(g, RECRUIT)
        self.play(g, P+'bounce', recruit); self.assertEqual(self.stats(g, 'hand'), [(2, 2)])
        self.play(g, RECRUIT); self.assertEqual(self.stats(g), [(2, 2)])
        self.assertEqual(g.state.entities[recruit].enchantments, [])

    def test_current_base_and_cross_player_copies_exclude_source_aura_cache(self):
        g = self.game((BLADE, P+'copy', P+'base', P+'other_copy', RECRUIT)); self.play(g)
        original = self.first(g, RECRUIT, 'hand')
        self.play(g, P+'copy', original); self.play(g, P+'base', original); self.play(g, P+'other_copy', original)
        self.assertEqual(self.stats(g, 'hand'), [(2, 2)]*3)
        self.assertEqual(self.stats(g, 'hand', p=2), [(1, 1)])
        self.portable(g)

    def test_dormant_recruit_keeps_controlled_card_stats(self):
        g = self.game((BLADE, P+'dormant'), board=(RECRUIT,)); self.play(g); recruit = self.first(g, RECRUIT)
        self.play(g, P+'dormant', recruit)
        self.assertFalse(g.state.entities[recruit].active)
        self.assertEqual(self.stats(g), [(2, 2)])
        self.portable(g)

    def test_dormant_global_cache_cannot_borrow_unbacked_attack_after_rehash(self):
        g = self.game((BLADE, P+'dormant'), board=(RECRUIT,)); self.play(g); recruit = self.first(g, RECRUIT)
        self.play(g, P+'dormant', recruit)
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(deepcopy(s), registry()).snapshot(), g.snapshot())
        s['state']['entities'][str(recruit)]['aura_attack'] += 1
        s['state_hash'] = canonical_hash({k: s[k] for k in ('ruleset', 'registry_fingerprint', 'mechanics_version',
            'state', 'rng_state', 'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(s, registry())
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_new_scope_requires_bounded_names_and_never_installs_missing_adapter(self):
        with self.assertRaises(ValueError): PlayerAuraSpec(1, 1, scope='controlled_minion_cards')
        with self.assertRaises(ValueError): PlayerAuraSpec(1, 1, (RECRUIT,), 'invented')
        r = registry(); self.assertIn('VAN_CS2_101t', r.player_effect(PREFIX+BLADE).auras[0].card_ids)
        self.assertNotIn('VAN_CS2_101t', r.cards)
        with self.assertRaisesRegex(ValueError, 'unsupported card definition'): r.card('VAN_CS2_101t')

    def test_projection_hides_enemy_stored_cards_and_no_private_global_ids(self):
        g = self.game((BLADE, RECRUIT), deck=(RECRUIT,)); self.play(g)
        own, enemy = json.dumps(g.for_player(1).observe()), json.dumps(g.for_player(2).observe())
        self.assertIn(RECRUIT, own)
        self.assertNotIn(RECRUIT, enemy)
        for text in (own, enemy, json.dumps(g.player_events(2))):
            self.assertNotIn('controlled_minion_cards', text)
            self.assertNotIn('recipient_ids', text)

    def test_current_assembly_adds_only_five_sources_and_preserves_old_definitions(self):
        with patch('hs_sim.cards.native_recruit_program_cards.register_native_recruit_program_cards', lambda r: None), \
                patch('hs_sim.cards.assemble_player_modifier_fragments.register_assemble_player_modifier_fragments', lambda r: None), \
                patch('hs_sim.cards.assemble_death_shield_inspire_followups.register_assemble_death_shield_inspire_followups', lambda r: None):
            before = build_registry()
        after = build_registry(); self.assertEqual(set(after.cards)-set(before.cards), set(ROOTS))
        for cid, card in before.cards.items(): self.assertEqual(asdict(card), asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards), dict(after.pool_cards))
        self.assertEqual(dict(before.pools), dict(after.pools))
        g = self.game(); s = g.snapshot(); s['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, registry())


if __name__ == '__main__': unittest.main()
