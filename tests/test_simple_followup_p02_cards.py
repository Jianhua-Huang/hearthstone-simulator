"""P02 real summon dependencies, physical facts and native continuation tests."""
from dataclasses import replace
import json
from random import Random
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p02_cards import (
    CROOK, MIRROR, DOOMSPEAKER, PREDATORS, DEFENSES, BLAZE,
    SHEEP, MAGE, SPITTER, SECURITY, ROOTS, DEPENDENCIES,
    load_batch, register_simple_followup_p02_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    SpellSchool, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.effects import (
    AddToHand, Buff, ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy,
    GrantKeyword, Heal, InvokeBehavior, ModifyWeapon, RequestChoice, Silence,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, DestroyStoredCard
from hs_sim.targets import canonical_digest

TEST = 'p02.test.'
YETI = 'CORE_CS2_182'
CHALLENGER = 'TLC_251'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def registry():
    r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS + DEPENDENCIES)
    if any(present) and not all(present):
        raise AssertionError('Partial P02 registration is not accepted')
    if not all(present):
        register_simple_followup_p02_cards(r)

    def summon(c, cid):
        return SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c))

    def fail(c):
        raise ResolutionError('P02 deliberate failure')

    def pair(c):
        return (DamageBatch((Damage(c.target_id, 1, c.source_id), Damage(c.target_id, 1, c.source_id))),)

    scripts = {
        'ping': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'hit2': lambda c: (Damage(c.target_id, 2, c.source_id),),
        'lethal': lambda c: (Damage(c.target_id, 30, c.source_id),),
        'zero': lambda c: (Damage(c.target_id, 0, c.source_id),),
        'pair': pair,
        'heal': lambda c: (Heal(c.target_id, 20, c.source_id),),
        'grow': lambda c: (Buff(c.target_id, 5, 5, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'immune': lambda c: (GrantKeyword(c.target_id, Keyword.IMMUNE, c.source_id),),
        'last': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, durability=-1),),
        'bare': lambda c: (CombatDamage(c.state.players[c.player_id].hero_id, c.state.players[2].hero_id),),
        'summon_blaze': lambda c: (summon(c, BLAZE),),
        'shadow': lambda c: (),
        'fire': lambda c: (),
    }
    for name, body in scripts.items():
        key = TEST + name
        r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.SPELL, on_play=key, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if name in ('ping', 'hit2', 'lethal', 'zero', 'pair', 'heal', 'grow', 'silence', 'kill', 'control', 'shield', 'immune') else None,
            spell_school=SpellSchool.SHADOW if name == 'shadow' else SpellSchool.FIRE if name == 'fire' else None))
    r.register_behavior(TEST+'fail', fail)
    for name, tribes in (('dragon', ('dragon',)), ('all', ('all',)), ('plain', ())):
        r.register_card(CardDefinition(TEST+name, name, CardType.MINION, attack=1, health=4,
                                       metadata=replace(META, tribes=tribes)))
    r.register_card(CardDefinition(TEST+'unknown', 'Unknown tribe', CardType.MINION, health=4))
    r.register_card(CardDefinition(TEST+'poison', 'Poison', CardType.MINION, attack=1, health=8,
                                   keywords=(Keyword.POISONOUS,), metadata=META))
    r.register_card(CardDefinition(TEST+'bonus', 'Spell damage', CardType.MINION, health=8, spell_damage=5, metadata=META))

    def summon_watch(c, cid):
        if c.state.entities[c.event.target_id].card_id != cid:
            return ()
        options = [ChoiceOption('ok', 'Continue', ()),
                   ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST+'fail', c.source_id, c.player_id),))]
        if cid == MAGE:
            dragon = next((c.state.entities[i] for i in c.state.players[c.player_id].hand
                           if c.state.entities[i].card_id == TEST+'dragon'), None)
            if dragon is not None:
                options.append(ChoiceOption('remove', 'Remove held Dragon',
                    (DestroyStoredCard(CardReference.capture(dragon), c.source_id),)))
            options.append(ChoiceOption('add', 'Add held Dragon', (AddToHand(c.player_id, TEST+'dragon', c.source_id),)))
        return (RequestChoice(c.player_id, tuple(options), source_id=c.source_id),)


    for name, cid in (('mirror_watch', MAGE), ('predator_watch', SPITTER), ('security_watch', SECURITY),
                       ('sheep_watch', SHEEP), ('blaze_watch', BLAZE)):
        key = TEST + name
        r.register_behavior(key, lambda c, cid=cid: summon_watch(c, cid))
        r.register_card(CardDefinition(key, name, CardType.MINION, health=10, metadata=META,
                                       triggers=(TriggerSpec('minion_summoned', key),)))
    r.validate()
    return r


class SimpleFollowupP02CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), deck=(YETI,)*10, seed=202):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40,
                        hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*10,
                        mana=40, max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), seed=seed), self.r)

    def entities(self, g, cid, p=1, zone='board'):
        return [g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid]

    def first(self, g, cid, p=1, zone='board'):
        return self.entities(g, cid, p, zone)[0]

    def play(self, g, cid, target=None):
        p = g.state.active_player
        source = self.first(g, cid, p, 'hand').id
        g.apply(PlayCard(p, source, target, len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None))
        return source

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for hidden in ('rng_state', 'resolution_frame', 'SummonEntryMaterial', 'CardReference', 'KindredActivation', 'checkpoint'):
                self.assertNotIn(hidden, public)
        return other

    def qualified(self, hand=(), board=(), enemy=()):
        g = self.game((TEST+'shadow', *hand), board, enemy)
        self.play(g, TEST+'shadow')
        self.cycle(g)
        return g


    def test_complete_raw_pins_ten_exact_faces_children_and_metadata(self):
        data = load_batch()
        self.assertEqual(tuple(row['record']['id'] for row in data['cards']), ROOTS)
        self.assertEqual(tuple(row['record']['id'] for row in data['dependencies']), DEPENDENCIES)
        observations = data['official_observations']['observations']
        self.assertEqual(len(observations), 20)
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])
        def normalize(text):
            return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', text)
        for row in data['cards'] + data['dependencies']:
            raw = row['record']
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            card = self.r.card(raw['id'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=card.id))
            self.assertEqual((card.cost, card.attack), (raw['cost'], raw['attack'] or 0))
            self.assertEqual(card.durability if card.kind == CardType.WEAPON else card.health if card.kind == CardType.MINION else None,
                             raw['health'])
            for obs in (o for o in observations if o['card_id'] == card.id):
                face = obs['face']
                english = obs['locale'] == 'en-us'
                self.assertEqual(face['name'], raw['name_en' if english else 'name'])
                self.assertEqual(normalize(face['text']), normalize(raw['text_en' if english else 'text']))
                for field, value in (('id', raw['dbf_id']), ('manaCost', raw['cost']), ('cardSetId', raw['card_set_id']),
                                     ('classId', raw['tags']['CLASS']), ('cardTypeId', raw['tags']['CARDTYPE'])):
                    self.assertEqual(face[field], value)
                if card.kind != CardType.SPELL:
                    self.assertEqual((face['attack'], face['health']), (card.attack, raw['health']))
        self.assertEqual(self.r.card(SHEEP).dormant_turns, 2)
        self.assertEqual(self.r.card(SPITTER).metadata.tribes, ('beast',))
        self.assertEqual(self.r.card(SPITTER).keywords, (Keyword.STEALTH, Keyword.POISONOUS))
        self.assertEqual(self.r.card(PREDATORS).spell_school, SpellSchool.SHADOW)
        self.assertIsNotNone(self.r.kindred_profiles[PREDATORS].prepare)

    def test_p02_preserves_skipped_doomspeaker_source_without_claiming_its_adapter(self):
        self.assertNotIn(DOOMSPEAKER, ROOTS)
        self.assertNotIn(DOOMSPEAKER, tuple(x['record']['id'] for x in load_batch()['cards']))
        row, = load_batch()['skipped']
        self.assertEqual(row['record']['id'], DOOMSPEAKER)
        self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertIn('discard_history.validate_boundary', row['reason'])

    def test_crook_last_completed_hero_attack_summons_native_dormant_sheep(self):
        g = self.game((CROOK, TEST+'last'))
        source = self.play(g, CROOK)
        self.play(g, TEST+'last')
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        sheep = self.first(g, SHEEP)
        self.assertEqual((sheep.attack, sheep.health, sheep.active, sheep.dormancy.remaining_turns), (3, 3, False, 2))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.hero(g, 2).health, 27)
        self.portable(g)

    def test_crook_minion_attack_and_invalid_bare_hero_combat_give_no_sheep(self):
        g = self.game((CROOK, TEST+'bare'), (YETI,))
        self.play(g, CROOK)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Bare hero combat'):
            self.play(g, TEST+'bare')
        self.assertEqual(g.snapshot(), saved)
        g.apply(Attack(1, self.first(g, YETI).id, self.hero(g, 2).id))
        self.assertFalse(self.entities(g, SHEEP))

    def test_crook_full_board_including_dormant_slots_cannot_summon(self):
        g = self.game((CROOK,), (SHEEP,)*7)
        self.play(g, CROOK)
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(len(self.entities(g, SHEEP)), 7)

    def test_sheep_wakes_on_second_owner_start_without_new_summon(self):
        g = self.game((CROOK,))
        self.play(g, CROOK)
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        original = self.first(g, SHEEP).id
        self.cycle(g)
        self.assertFalse(g.state.entities[original].active)
        self.assertEqual(g.state.entities[original].dormancy.remaining_turns, 1)
        self.cycle(g)
        self.assertTrue(g.state.entities[original].active)
        self.assertIsNone(g.state.entities[original].dormancy)
        self.assertEqual(len([e for e in g.events if e.kind == 'minion_summoned' and e.target_id == original]), 1)

    def test_crook_summon_wait_can_restore_after_weapon_death(self):
        g = self.game((CROOK, TEST+'last'), (TEST+'sheep_watch',))
        weapon = self.play(g, CROOK)
        self.play(g, TEST+'last')
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.entities(g, SHEEP)), 1)

    def test_mirror_no_dragon_summons_one_exact_zero_four_taunt(self):
        g = self.game((MIRROR, YETI))
        source = self.play(g, MIRROR)
        mage = self.first(g, MAGE)
        self.assertEqual((mage.attack, mage.health, mage.keywords), (0, 4, frozenset((Keyword.TAUNT,))))
        self.assertEqual(len(self.entities(g, MAGE)), 1)
        self.assertEqual(g.state.players[1].mana, 39)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.cast_id, g.state.cast_history[-1].id)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id, source)

    def test_mirror_held_dragon_or_all_summons_two_but_board_or_enemy_does_not(self):
        for cid in (TEST+'dragon', TEST+'all'):
            g = self.game((MIRROR, cid))
            self.play(g, MIRROR)
            self.assertEqual(len(self.entities(g, MAGE)), 2)
        g = self.game((MIRROR,), (TEST+'dragon',), enemy_hand=(TEST+'dragon',))
        self.play(g, MIRROR)
        self.assertEqual(len(self.entities(g, MAGE)), 1)

    def test_mirror_checks_actual_hand_after_first_summon_reaction(self):
        g = self.game((MIRROR, TEST+'dragon'), (TEST+'mirror_watch',))
        self.play(g, MIRROR)
        self.choose(g, 'remove')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(self.entities(g, MAGE)), 1)
        h = self.game((MIRROR,), (TEST+'mirror_watch',))
        self.play(h, MIRROR)
        other = self.portable(h)
        self.choose(h, 'add')
        self.choose(other, 'add')
        self.assertEqual(h.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(h, MAGE)), 2)
        self.choose(h)
        self.portable(h)

    def test_mirror_unknown_held_tribe_rolls_back_instead_of_silent_no_dragon(self):
        g = self.game((MIRROR, TEST+'unknown'))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'):
            self.play(g, MIRROR)
        self.assertEqual(g.snapshot(), saved)

    def test_mirror_respects_one_or_zero_available_slots(self):
        for count, expected in ((6, 1), (7, 0)):
            g = self.game((MIRROR, TEST+'dragon'), (YETI,)*count)
            self.play(g, MIRROR)
            self.assertEqual(len(self.entities(g, MAGE)), expected)






    def test_predators_unqualified_prepare_always_summons_one_real_spitter(self):
        g = self.game((PREDATORS,))
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 1)
        self.assertEqual(self.first(g, SPITTER).keywords, frozenset((Keyword.STEALTH, Keyword.POISONOUS)))
        row = g.state.kindred_history[-1]
        self.assertFalse(row.condition.matched)
        self.assertEqual(row.plan, ('prepare',))
        self.assertTrue(row.completed)

    def test_predators_previous_owner_shadow_qualifies_even_with_later_unrelated_play(self):
        g = self.game((TEST+'shadow', TEST+'fire', PREDATORS))
        self.play(g, TEST+'shadow')
        self.play(g, TEST+'fire')
        self.cycle(g)
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 2)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare', 'active'))
        self.assertTrue(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(g.state.players[1].mana, 37)

    def test_predators_same_turn_and_opponent_shadow_do_not_qualify(self):
        g = self.game((TEST+'shadow', PREDATORS))
        self.play(g, TEST+'shadow')
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 1)
        h = self.game((PREDATORS,), enemy_hand=(TEST+'shadow',))
        h.apply(EndTurn(1))
        self.play(h, TEST+'shadow')
        h.apply(EndTurn(2))
        self.play(h, PREDATORS)
        self.assertEqual(len(self.entities(h, SPITTER)), 1)

    def test_predators_old_qualifying_turn_is_replaced_by_latest_empty_owner_turn(self):
        g = self.qualified((PREDATORS,))
        self.cycle(g)
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 1)

    def test_predators_next_kindred_repeats_only_active_not_ordinary_summon(self):
        g = self.qualified((CHALLENGER, PREDATORS))
        self.play(g, CHALLENGER)
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 3)
        row = g.state.kindred_history[-1]
        self.assertEqual((row.plan, row.repetitions, row.completed), (('prepare', 'active', 'active'), 2, True))
        self.assertEqual(len(row.sources), 1)
        self.assertFalse(g.state.players[1].player_effects)

    def test_predators_accepted_plan_wait_failure_and_shared_recovery(self):
        g = self.qualified((PREDATORS,), board=(TEST+'predator_watch',))
        self.play(g, PREDATORS)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(g, SPITTER)), 2)
        self.choose(g)
        self.assertTrue(g.state.kindred_history[-1].completed)
        self.portable(g)

    def test_predators_capacity_caps_physical_delivery_not_accepted_plan(self):
        g = self.qualified((PREDATORS,), board=(YETI,)*6)
        self.play(g, PREDATORS)
        self.assertEqual(len(self.entities(g, SPITTER)), 1)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare', 'active'))
        self.assertTrue(g.state.kindred_history[-1].completed)

    def test_security_two_exact_taunts_and_positive_damage_packets_gain_attack(self):
        g = self.game((DEFENSES, TEST+'hit2', TEST+'pair'))
        self.play(g, DEFENSES)
        guards = self.entities(g, SECURITY)
        self.assertEqual(len(guards), 2)
        self.assertTrue(all((e.attack, e.health, e.keywords) == (0, 6, frozenset((Keyword.TAUNT,))) for e in guards))
        self.play(g, TEST+'hit2', guards[0].id)
        self.assertEqual((g.state.entities[guards[0].id].attack, g.state.entities[guards[0].id].health), (1, 4))
        self.play(g, TEST+'pair', guards[1].id)
        self.assertEqual((g.state.entities[guards[1].id].attack, g.state.entities[guards[1].id].health), (2, 4))

    def test_security_zero_damage_heal_prevention_and_other_target_do_not_buff(self):
        for action in ('zero', 'heal', 'shield', 'immune'):
            with self.subTest(action=action):
                g = self.game((TEST+action, TEST+'ping'), (SECURITY, YETI))
                target = self.first(g, SECURITY).id
                self.play(g, TEST+action, target)
                self.play(g, TEST+'ping', target if action in ('shield', 'immune') else self.first(g, YETI).id)
                self.assertEqual(g.state.entities[target].attack, 0)

    def test_security_silence_removes_taunt_and_damage_trigger(self):
        g = self.game((TEST+'silence', TEST+'ping'), (SECURITY,))
        target = self.first(g, SECURITY).id
        self.play(g, TEST+'silence', target)
        self.play(g, TEST+'ping', target)
        self.assertEqual(g.state.entities[target].attack, 0)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[target].keywords)

    def test_security_control_change_preserves_own_original_damage_trigger(self):
        g = self.game((TEST+'control', TEST+'ping'), (SECURITY,))
        target = self.first(g, SECURITY).id
        self.play(g, TEST+'control', target)
        self.play(g, TEST+'ping', target)
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].attack), (2, 1))

    def test_security_full_or_one_slot_and_second_summon_wait_restores(self):
        for count, expected in ((6, 1), (7, 0)):
            g = self.game((DEFENSES,), (YETI,)*count)
            self.play(g, DEFENSES)
            self.assertEqual(len(self.entities(g, SECURITY)), expected)
        h = self.game((DEFENSES,), (TEST+'security_watch',))
        self.play(h, DEFENSES)
        other = self.portable(h)
        self.choose(h)
        self.choose(other)
        self.assertEqual(h.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(h, SECURITY)), 2)
        self.choose(h)

    def test_blaze_survived_damage_summons_new_base_not_current_copy(self):
        g = self.game((TEST+'grow', TEST+'ping'), (BLAZE,))
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'grow', source)
        self.play(g, TEST+'ping', source)
        original, fresh = self.entities(g, BLAZE)
        self.assertEqual((original.attack, original.health), (8, 7))
        self.assertNotEqual(original.id, fresh.id)
        self.assertEqual((fresh.attack, fresh.health, fresh.enchantments), (3, 3, []))
        self.assertTrue(fresh.abilities)

    def test_blaze_each_survived_damage_packet_adds_one_base_entity(self):
        g = self.game((TEST+'pair',), (BLAZE,))
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'pair', source)
        self.assertEqual(len(self.entities(g, BLAZE)), 3)
        self.assertEqual(g.state.entities[source].health, 1)

    def test_blaze_lethal_or_poison_damage_does_not_summon_replacement(self):
        g = self.game((TEST+'lethal',), (BLAZE,))
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'lethal', source)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(self.entities(g, BLAZE))
        h = self.game(board=(TEST+'poison',), enemy=(BLAZE,))
        target = self.first(h, BLAZE, 2).id
        h.apply(Attack(1, self.first(h, TEST+'poison').id, target))
        self.assertEqual(h.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertFalse(self.entities(h, BLAZE, 2))

    def test_blaze_shield_immune_zero_heal_or_other_damage_does_not_clone(self):
        for action in ('zero', 'heal', 'shield', 'immune'):
            g = self.game((TEST+action, TEST+'ping'), (BLAZE, YETI))
            target = self.first(g, BLAZE).id
            self.play(g, TEST+action, target)
            self.play(g, TEST+'ping', target if action in ('shield', 'immune') else self.first(g, YETI).id)
            self.assertEqual(len(self.entities(g, BLAZE)), 1)

    def test_blaze_full_board_does_not_replace_or_copy_source(self):
        g = self.game((TEST+'ping',), (BLAZE,)+(YETI,)*6)
        self.play(g, TEST+'ping', self.first(g, BLAZE).id)
        self.assertEqual(len(self.entities(g, BLAZE)), 1)
        self.assertEqual(len(g.state.players[1].board), 7)

    def test_blaze_deathrattle_is_one_two_damage_minion_ability_not_spell(self):
        g = self.game((TEST+'kill',), (BLAZE, TEST+'bonus'))
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'kill', source)
        hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
        self.assertEqual([e.amount for e in hits], [2])
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertEqual(len([e for e in g.events if e.kind == 'random_choice' and e.source_id == source]), 1)

    def test_blaze_silence_removes_survival_summon_and_deathrattle(self):
        g = self.game((TEST+'silence', TEST+'ping', TEST+'kill'), (BLAZE,))
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'silence', source)
        self.play(g, TEST+'ping', source)
        self.assertEqual(len(self.entities(g, BLAZE)), 1)
        self.play(g, TEST+'kill', source)
        self.assertEqual(self.hero(g, 2).health, 30)

    def test_blaze_control_change_uses_new_owner_for_summon_and_deathrattle(self):
        g = self.game((TEST+'control', TEST+'ping', TEST+'kill'), (BLAZE,), seed=8)
        source = self.first(g, BLAZE).id
        self.play(g, TEST+'control', source)
        self.play(g, TEST+'ping', source)
        self.assertEqual(len(self.entities(g, BLAZE, 2)), 2)
        self.play(g, TEST+'kill', source)
        self.assertEqual(self.hero(g).health, 28)
        self.assertEqual(self.hero(g, 2).health, 30)

    def test_blaze_summon_wait_failure_rolls_back_choice_and_restores_actual_new_entity(self):
        g = self.game((TEST+'ping',), (TEST+'blaze_watch', BLAZE))
        self.play(g, TEST+'ping', self.first(g, BLAZE).id)
        self.assertEqual(len(self.entities(g, BLAZE)), 2)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())


if __name__ == '__main__':
    unittest.main()
