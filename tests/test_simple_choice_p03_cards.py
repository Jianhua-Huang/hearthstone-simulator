"""Real P03 branches, original hand rewards and exact dependency behavior."""
from dataclasses import asdict, replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_choice_p03_cards import (
    KEEPER, RELEASE, FOREST, GRACE, THORN, SWORD, WOLF, FALCON, PUP,
    FOREST_WOLVES, FOREST_FALCONS, GRACE_DAMAGE, GRACE_PUPS,
    ROOTS, DEPENDENCIES, CHOICE_ONLY, load_batch, register_simple_choice_p03_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    SpellSchool, TriggerSpec, Zone,
)
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, DestroyStoredCard, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p03.test.'
YETI = 'CORE_CS2_182'
FIREBALL = 'CORE_CS2_029'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


def registry():
    r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS + DEPENDENCIES)
    if any(present) and not all(present):
        raise AssertionError('Partial P03 registration is not accepted')
    if not all(present):
        register_simple_choice_p03_cards(r)
    for name, tribes, rarity in (('plain', (), Rarity.COMMON), ('legend', (), Rarity.LEGENDARY),
                                 ('dragon', ('dragon',), Rarity.COMMON), ('all', ('all',), Rarity.COMMON)):
        r.register_card(CardDefinition(TEST+name, 'P03 '+name, CardType.MINION, attack=2, health=3,
                                       metadata=replace(META, tribes=tribes, rarity=rarity)))
    r.register_card(CardDefinition(TEST+'unknown_rarity', 'Unknown rarity', CardType.MINION, health=3,
                                   metadata=replace(META, rarity=None)))
    r.register_card(CardDefinition(TEST+'unknown_tribes', 'Unknown tribes', CardType.MINION, health=3))
    r.register_card(CardDefinition(TEST+'bonus', 'Spell damage', CardType.MINION, health=8, spell_damage=1, metadata=META))
    r.register_card(CardDefinition(TEST+'both', 'Existing ordinary Choose Both', CardType.MINION, health=8,
                                   choose_both=True, metadata=META))
    r.register_behavior(TEST+'fail', lambda c: (AddToHand(c.player_id, 'p03.missing'),))

    def waiting(c, extra=()):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST+'fail', c.source_id, c.player_id),)),
            *extra,
        ), source_id=c.source_id),)

    def keeper_entry(c):
        if c.state.entities[c.event.target_id].card_id != KEEPER:
            return ()
        dragon = next((c.state.entities[i] for i in c.state.players[c.player_id].hand
                       if c.state.entities[i].card_id == TEST+'dragon'), None)
        extra = [ChoiceOption('add', 'Add actual held Dragon', (AddToHand(c.player_id, TEST+'dragon', c.source_id),))]
        if dragon is not None:
            extra.append(ChoiceOption('remove', 'Remove held Dragon',
                (DestroyStoredCard(CardReference.capture(dragon), c.source_id),)))
        return waiting(c, tuple(extra))

    def release_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != RELEASE:
            return ()
        target = c.state.entities[c.event.target_id]
        if target.card_id != TEST+'plain':
            return ()
        original = next((c.state.entities[i] for i in c.state.players[c.player_id].hand
                         if c.state.entities[i].card_id == TEST+'legend'), None)
        extra = [ChoiceOption('add', 'Add new Legendary', (AddToHand(c.player_id, TEST+'legend', c.source_id),))]
        if original is not None:
            extra.append(ChoiceOption('replace', 'Replace original Legendary', (
                DestroyStoredCard(CardReference.capture(original), c.source_id),
                AddToHand(c.player_id, TEST+'legend', c.source_id),)))
            extra.append(ChoiceOption('move', 'Move original to deck', (
                MoveCard(CardReference.capture(original), c.player_id, Zone.DECK, source_id=c.source_id),)))
        return waiting(c, tuple(extra))

    def summon_wait(c):
        if c.state.entities[c.event.target_id].card_id not in (WOLF, FALCON, PUP):
            return ()
        return waiting(c)

    for name, event, body in (('keeper_entry', 'minion_summoned', keeper_entry),
                              ('release_wait', 'stored_card_buffed', release_wait),
                              ('summon_wait', 'minion_summoned', summon_wait)):
        r.register_behavior(TEST+name, body)
        r.register_card(CardDefinition(TEST+name, name, CardType.MINION, health=10, metadata=META,
                                       triggers=(TriggerSpec(event, TEST+name),)))
    r.register_behavior(TEST+'weapon_death', lambda c: waiting(c))
    r.register_card(CardDefinition(TEST+'weapon', 'Replaceable weapon', CardType.WEAPON, attack=1, durability=1,
                                   deathrattle=TEST+'weapon_death', metadata=META))
    r.register_behavior(TEST+'auto_grace', lambda c: (CastSpell(c.player_id, GRACE, c.source_id, branch_id=GRACE_DAMAGE),))
    r.register_card(CardDefinition(TEST+'auto_grace', 'Automatic Grace', CardType.SPELL, on_play=TEST+'auto_grace', metadata=META))
    r.validate()
    return r


class SimpleChoiceP03CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), deck=(YETI,)*8, weapon=None, seed=303):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40,
                        weapon_card_id=weapon, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8,
                        mana=40, max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), seed=seed), self.r)

    def entities(self, g, cid, p=1, zone='board'):
        return [g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid]

    def first(self, g, cid, p=1, zone='board'):
        return self.entities(g, cid, p, zone)[0]

    def play(self, g, cid, branch=None):
        p = g.state.active_player
        source = self.first(g, cid, p, 'hand').id
        g.apply(PlayCard(p, source, position=len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None,
                         branch_id=branch))
        return source

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for hidden in ('rng_state', 'resolution_frame', 'SummonEntryMaterial', 'CardReference', 'behavior_id', 'checkpoint'):
                self.assertNotIn(hidden, public)
        return other

    def test_complete_raw_pins_official_faces_and_exact_cross_set_dependencies(self):
        d = load_batch()
        self.assertEqual(tuple(row['record']['id'] for row in d['cards']), ROOTS)
        self.assertEqual(tuple(row['record']['id'] for row in d['dependencies']), DEPENDENCIES)
        observations = d['official_observations']['observations']
        self.assertEqual(len(observations), 30)
        self.assertFalse(d['formal_pool_complete'])
        self.assertFalse(d['cn_calibrated'])
        def normalize(s):
            return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        for group in ('cards', 'dependencies', 'existing_dependencies', 'skipped', 'evidence_only'):
            for row in d[group]:
                raw = row['record']
                self.assertEqual(canonical_digest(raw), row['record_sha256'])
                for obs in (o for o in observations if o['card_id'] == raw['id']):
                    face = obs['face']
                    en = obs['locale'] == 'en-us'
                    self.assertEqual(face['name'], raw['name_en' if en else 'name'])
                    self.assertEqual(normalize(face['text']), normalize(raw['text_en' if en else 'text']))
                    for k, value in (('id', raw['dbf_id']), ('manaCost', raw['cost']), ('classId', raw['tags']['CLASS']),
                                     ('cardSetId', raw['card_set_id']), ('cardTypeId', raw['tags']['CARDTYPE'])):
                        self.assertEqual(face[k], value)
        for row in d['cards'] + d['dependencies']:
            raw = row['record']
            card = self.r.card(raw['id'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=card.id))
            self.assertEqual(card.cost, 0 if card.choice_only else raw['cost'])
            self.assertEqual(card.attack, raw['attack'] or 0)
            self.assertEqual(card.durability if card.kind == CardType.WEAPON else card.health if card.kind == CardType.MINION else None, raw['health'])
        reused, = d['existing_dependencies']
        self.assertEqual(canonical_digest(asdict(self.r.card(PUP))), reused['definition_sha256'])
        for cid in (WOLF, FALCON, PUP):
            self.assertEqual(set(self.r.card(cid).metadata.tribes), {'beast', 'undead'})
        self.assertEqual(self.r.card(FOREST).spell_school, SpellSchool.NATURE)

    def test_thorn_remains_evidence_only_as_real_unsupported_weapon_choice_root(self):
        d = load_batch()
        row, = d['skipped']
        self.assertEqual((row['record']['id'], row['record']['type']), (THORN, 'WEAPON'))
        self.assertNotIn(THORN, ROOTS + DEPENDENCIES)
        self.assertIn('choose_one.normalize', row['reason'])
        self.assertEqual(tuple(x['record']['id'] for x in d['evidence_only']), ('EDR_525A', 'EDR_525B'))

    def test_choice_descriptors_preserve_raw_but_are_nonphysical_not_pool_cards(self):
        for cid in CHOICE_ONLY:
            card = self.r.card(cid)
            self.assertTrue(card.choice_only)
            self.assertFalse(card.hand_playable)
            self.assertEqual(card.cost, 0)
            self.assertNotIn(cid, self.r.pool_cards)
        self.assertEqual(tuple(b.id for b in self.r.card(FOREST).choose_one.branches), (FOREST_WOLVES, FOREST_FALCONS))
        self.assertEqual(tuple(b.id for b in self.r.card(GRACE).choose_one.branches), (GRACE_DAMAGE, GRACE_PUPS))

    def test_keeper_actual_held_dragon_and_all_equips_exact_two_two_sword(self):
        for cid in (TEST+'dragon', TEST+'all'):
            g = self.game((KEEPER, cid))
            self.play(g, KEEPER)
            sword = g.state.entities[g.state.players[1].weapon_id]
            self.assertEqual((sword.card_id, sword.attack, sword.durability), (SWORD, 2, 2))
            self.assertEqual(g.state.players[1].mana, 38)

    def test_keeper_board_enemy_and_non_dragon_hand_do_not_equip(self):
        g = self.game((KEEPER, YETI), (TEST+'dragon',), enemy_hand=(TEST+'dragon',))
        self.play(g, KEEPER)
        self.assertIsNone(g.state.players[1].weapon_id)

    def test_keeper_reads_actual_hand_after_entry_reactions(self):
        g = self.game((KEEPER,), (TEST+'keeper_entry',))
        self.play(g, KEEPER)
        self.choose(g, 'add')
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id, SWORD)
        h = self.game((KEEPER, TEST+'dragon'), (TEST+'keeper_entry',))
        self.play(h, KEEPER)
        self.choose(h, 'remove')
        self.assertIsNone(h.state.players[1].weapon_id)

    def test_keeper_unknown_held_tribe_rolls_back_instead_of_silent_nonmatch(self):
        g = self.game((KEEPER, TEST+'unknown_tribes'))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'):
            self.play(g, KEEPER)
        self.assertEqual(g.snapshot(), saved)

    def test_keeper_weapon_replacement_uses_original_death_wait_and_portable_state(self):
        g = self.game((KEEPER, TEST+'dragon'), weapon=TEST+'weapon')
        old = g.state.players[1].weapon_id
        self.play(g, KEEPER)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id, SWORD)
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual(self.hero(g, 2).health, 28)

    def test_release_all_original_hand_minions_legendary_receives_extra(self):
        g = self.game((RELEASE, TEST+'plain', TEST+'legend', FIREBALL, SWORD), (TEST+'plain',),
                      enemy_hand=(TEST+'legend',), deck=(TEST+'legend',))
        self.play(g, RELEASE)
        self.assertEqual((self.first(g, TEST+'plain', zone='hand').attack, self.first(g, TEST+'plain', zone='hand').max_health), (3, 4))
        self.assertEqual((self.first(g, TEST+'legend', zone='hand').attack, self.first(g, TEST+'legend', zone='hand').max_health), (5, 5))
        self.assertEqual(self.first(g, TEST+'plain').attack, 2)
        self.assertEqual(self.first(g, TEST+'legend', 2, 'hand').attack, 2)
        self.assertEqual(self.first(g, TEST+'legend', zone='deck').attack, 2)
        self.assertEqual(self.first(g, SWORD, zone='hand').attack, 2)
        self.assertEqual(g.state.players[1].mana, 38)

    def test_release_unknown_rarity_is_explicit_error_and_atomic_rollback(self):
        g = self.game((RELEASE, TEST+'plain', TEST+'unknown_rarity'))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown candidate rarity'):
            self.play(g, RELEASE)
        self.assertEqual(g.snapshot(), saved)

    def test_release_empty_hand_minion_pool_does_not_use_rng_or_draw(self):
        g = self.game((RELEASE, FIREBALL, SWORD))
        before = g.snapshot()['rng_state']
        self.play(g, RELEASE)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertFalse(g.state.draw_history)

    def test_release_new_legendary_after_first_reward_gets_neither_old_reward(self):
        g = self.game((RELEASE, TEST+'plain', TEST+'legend'), (TEST+'release_wait',))
        original = self.first(g, TEST+'legend', zone='hand').id
        self.play(g, RELEASE)
        other = self.portable(g)
        self.choose(g, 'add')
        self.choose(other, 'add')
        self.assertEqual(g.snapshot(), other.snapshot())
        legendaries = self.entities(g, TEST+'legend', zone='hand')
        self.assertEqual([(e.attack, e.max_health) for e in legendaries], [(5, 5), (2, 3)])
        self.assertEqual(legendaries[0].id, original)
        self.assertNotIn('P03 legend', json.dumps(g.for_player(2).observe()))
        self.portable(g)

    def test_release_replacement_and_moved_original_do_not_receive_captured_rewards(self):
        for action in ('replace', 'move'):
            g = self.game((RELEASE, TEST+'plain', TEST+'legend'), (TEST+'release_wait',))
            original = self.first(g, TEST+'legend', zone='hand').id
            self.play(g, RELEASE)
            self.choose(g, action)
            self.assertEqual((g.state.entities[original].attack, g.state.entities[original].max_health), (2, 3))
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD if action == 'replace' else Zone.DECK)
            if action == 'replace':
                fresh = self.first(g, TEST+'legend', zone='hand')
                self.assertNotEqual(fresh.id, original)
                self.assertEqual((fresh.attack, fresh.max_health), (2, 3))

    def test_release_failing_choice_rolls_back_to_reward_wait_without_repayment(self):
        g = self.game((RELEASE, TEST+'plain', TEST+'legend'), (TEST+'release_wait',))
        self.play(g, RELEASE)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.assertEqual(self.first(g, TEST+'legend', zone='hand').attack, 5)
        self.assertEqual(g.state.players[1].mana, 38)

    def test_forest_wolf_branch_summons_three_exact_taunt_dual_tribe_bodies(self):
        g = self.game((FOREST,))
        source = self.play(g, FOREST, FOREST_WOLVES)
        wolves = self.entities(g, WOLF)
        self.assertEqual(len(wolves), 3)
        self.assertTrue(all((e.attack, e.health, e.keywords) == (2, 3, frozenset((Keyword.TAUNT,))) for e in wolves))
        self.assertFalse(self.entities(g, FALCON))
        self.assertEqual(g.state.players[1].mana, 35)
        self.assertEqual(g.state.cast_history[-1].branch_id, FOREST_WOLVES)
        self.assertTrue(all(row.request.cause.cast_id == g.state.cast_history[-1].id and row.request.cause.source.entity_id == source
                            for row in g.state.card_summon_history))

    def test_forest_falcon_branch_summons_two_four_three_windfury_bodies(self):
        g = self.game((FOREST,))
        self.play(g, FOREST, FOREST_FALCONS)
        falcons = self.entities(g, FALCON)
        self.assertEqual(len(falcons), 2)
        self.assertTrue(all((e.attack, e.health, e.keywords) == (4, 3, frozenset((Keyword.WINDFURY,))) for e in falcons))
        self.assertFalse(self.entities(g, WOLF))
        self.assertIsNone(g.state.pending_choice)

    def test_choose_one_rejects_missing_unknown_or_other_root_branch_before_payment(self):
        for cid, invalid in ((FOREST, None), (FOREST, 'unknown'), (GRACE, FOREST_WOLVES)):
            g = self.game((cid,))
            saved = g.snapshot()
            with self.assertRaises(IllegalAction):
                self.play(g, cid, invalid)
            self.assertEqual(g.snapshot(), saved)

    def test_forest_capacity_preserves_selected_plan_but_caps_deliveries(self):
        for count, expected in ((6, 1), (7, 0)):
            g = self.game((FOREST,), (YETI,)*count)
            self.play(g, FOREST, FOREST_WOLVES)
            self.assertEqual(len(self.entities(g, WOLF)), expected)
            self.assertEqual(g.state.players[1].mana, 35)

    def test_forest_selected_branch_summon_wait_preserves_tail_and_rolls_back_failure(self):
        g = self.game((FOREST,), (TEST+'summon_wait',))
        self.play(g, FOREST, FOREST_WOLVES)
        self.assertEqual(len(self.entities(g, WOLF)), 1)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.drain(g)
        self.assertEqual(len(self.entities(g, WOLF)), 3)
        self.portable(g)

    def test_grace_fixed_enemy_hero_damage_is_spell_attributed_and_receives_spell_bonus(self):
        g = self.game((GRACE,), (TEST+'bonus',))
        source = self.play(g, GRACE, GRACE_DAMAGE)
        self.assertEqual(self.hero(g, 2).health, 25)
        self.assertEqual(self.hero(g).health, 30)
        self.assertFalse(self.entities(g, PUP))
        hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
        self.assertEqual([e.amount for e in hits], [5])
        self.assertEqual(g.state.players[1].mana, 36)

    def test_grace_summons_two_exact_existing_rush_pups_without_damage(self):
        g = self.game((GRACE,), enemy=(YETI,))
        self.play(g, GRACE, GRACE_PUPS)
        pups = self.entities(g, PUP)
        self.assertEqual(len(pups), 2)
        self.assertTrue(all((e.attack, e.health, e.keywords) == (3, 2, frozenset((Keyword.RUSH,))) for e in pups))
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, pups[0].id, self.hero(g, 2).id))
        self.assertEqual(g.snapshot(), saved)
        g.apply(Attack(1, pups[0].id, self.first(g, YETI, 2).id))
        self.assertEqual(self.first(g, YETI, 2).health, 2)
        self.assertEqual(self.hero(g, 2).health, 30)

    def test_grace_pup_summon_wait_has_original_cast_and_selected_branch_after_restore(self):
        g = self.game((GRACE,), (TEST+'summon_wait',))
        self.play(g, GRACE, GRACE_PUPS)
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.choose(g)
        self.assertEqual(len(self.entities(g, PUP)), 2)
        self.assertEqual(g.state.cast_history[-1].branch_id, GRACE_PUPS)

    def test_grace_automatic_cast_uses_same_spell_payload_and_explicit_native_branch(self):
        g = self.game((TEST+'auto_grace',), (TEST+'bonus',))
        self.play(g, TEST+'auto_grace')
        self.assertEqual(self.hero(g, 2).health, 25)
        self.assertEqual(g.state.cast_history[-1].card_id, GRACE)
        self.assertEqual(g.state.cast_history[-1].branch_id, GRACE_DAMAGE)
        self.assertEqual(g.state.cast_history[-1].origin, 'effect')

    def test_required_existing_combined_bodies_share_one_payment_and_original_cast(self):
        for cid in (FOREST, GRACE):
            g = self.game((cid,), (TEST+'both',))
            source = self.play(g, cid, cid+':combined')
            if cid == FOREST:
                self.assertEqual((len(self.entities(g, WOLF)), len(self.entities(g, FALCON))), (3, 2))
            else:
                self.assertEqual((self.hero(g, 2).health, len(self.entities(g, PUP))), (26, 2))
            self.assertEqual(g.state.players[1].mana, 40-self.r.card(cid).cost)
            self.assertEqual(len(g.state.cast_history), 1)
            self.assertTrue(all(row.request.cause.source.entity_id == source for row in g.state.card_summon_history))

    def test_native_choices_are_public_branch_labels_without_internal_behavior_or_extra_choice(self):
        g = self.game((FOREST, GRACE))
        actions = json.dumps(g.for_player(1).legal_actions())
        self.assertIn(FOREST_WOLVES, actions)
        self.assertIn(FOREST_FALCONS, actions)
        self.assertIn(GRACE_DAMAGE, actions)
        self.assertNotIn('cards.simple_choice_p03', actions)
        self.assertNotIn(FOREST_WOLVES, json.dumps(g.for_player(2).observe()))
        self.play(g, FOREST, FOREST_FALCONS)
        self.assertIsNone(g.state.pending_choice)


if __name__ == '__main__':
    unittest.main()
