"""P01 real effects, limited dependency checks, and shared portable boundaries."""
from dataclasses import replace
import json
from random import Random
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.parallel_trial_p01_cards import (
    CLAW, DOVE, DINOMANCY, STONECARVER, KROG, TENDER, DAGGERS, REND,
    ROOTS, load_batch, register_parallel_trial_p01_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, UseHandAction, Zone,
)
from hs_sim.engine.effects import (
    AddToHand, Buff, ChangeControl, ChoiceOption, Damage, Destroy, Draw,
    Heal, InvokeBehavior, ModifyWeapon, RequestChoice, ReturnToHand, Silence,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose, DamageKind, TribeChangeSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, DestroyStoredCard
from hs_sim.targets import canonical_digest

YETI = 'CORE_CS2_182'
FIREBALL = 'CORE_CS2_029'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
TEST = 'p01.test.'


def registry():
    r = build_registry()
    # The coordinator may later add this whole batch to the shared builder.
    present = tuple(cid in r.cards for cid in ROOTS)
    if any(present) and not all(present):
        raise AssertionError('Partially registered P01 is not an accepted registry')
    if not all(present):
        register_parallel_trial_p01_cards(r)
    r.register_behavior(TEST + 'noop', lambda c: ())

    def first(c, cid, player=None, zone='board'):
        return next(c.state.entities[i] for i in getattr(c.state.players[player or c.player_id], zone)
                    if c.state.entities[i].card_id == TEST + cid)

    def fail(c):
        raise ResolutionError('P01 deliberate failure')

    def draw_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != DOVE:
            return ()
        target = c.event.target_id
        return (RequestChoice(c.player_id, (
            ChoiceOption('leave', 'Leave hand', ()),
            ChoiceOption('replace', 'Remove drawn minion and add another', (
                DestroyStoredCard(CardReference.capture(c.state.entities[target]), c.source_id),
                AddToHand(c.player_id, TEST + 'beast', c.source_id))),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    def damage_wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in (DAGGERS, REND):
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('add', 'Add enemy minion', (AddToHand(2, TEST + 'beast', c.source_id),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    def remove_weapon(c):
        wid = c.state.players[3-c.player_id].weapon_id
        return (Destroy(wid, c.source_id),) if wid is not None and c.event.player_id != c.player_id else ()

    def dove_entry(c):
        return (AddToHand(c.player_id, TEST+'plain', c.source_id),) if c.state.entities[c.event.target_id].card_id == DOVE else ()

    scripts = {
        'hurt': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'heal': lambda c: (Heal(c.target_id, 20, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'beastify': lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
                                               TribeChangeSpec('set', ('beast',)), c.source_id),),
        'unbeast': lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
                                              TribeChangeSpec('set', ('dragon',)), c.source_id),),
        'last': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, durability=-1),),
        'bare': lambda c: (CombatDamage(c.state.players[c.player_id].hero_id, c.state.players[2].hero_id),),
        'buff': lambda c: (Buff(c.target_id, 3, 4, c.source_id),),
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'wound_hero': lambda c: (Damage(c.state.players[2].hero_id, 26, c.source_id),),
    }
    for key, body in scripts.items():
        name = TEST + key
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, key, CardType.SPELL, on_play=name, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if key in ('hurt', 'heal', 'silence', 'control', 'beastify', 'unbeast', 'buff') else None))
    r.register_behavior(TEST + 'fail', fail)
    for key, attack, health, tribes in (
        ('beast', 2, 3, ('beast',)), ('all', 2, 3, ('all',)), ('plain', 2, 3, ()),
        ('tiny', 0, 1, ()), ('dragon', 2, 3, ('dragon',)),
    ):
        r.register_card(CardDefinition(TEST + key, key, CardType.MINION, attack=attack, health=health,
                                       metadata=replace(META, tribes=tribes)))
    r.register_card(CardDefinition(TEST + 'unknown', 'Unknown tribes', CardType.MINION, health=3))
    r.register_card(CardDefinition(TEST + 'bonus', 'Spell damage', CardType.MINION, health=8, spell_damage=1, metadata=META))
    r.register_card(CardDefinition(TEST + 'shield', 'Shield', CardType.MINION, health=8,
                                   keywords=(Keyword.DIVINE_SHIELD,), metadata=META))
    r.register_card(CardDefinition(TEST + 'sleep', 'Dormant Beast', CardType.MINION, health=8, dormant_turns=2,
                                   metadata=replace(META, tribes=('beast',))))
    r.register_card(CardDefinition(TEST + 'location', 'Location', CardType.LOCATION, durability=3, on_use=TEST + 'noop', metadata=META))
    for key, event, body in (('draw_wait', 'card_drawn', draw_wait), ('damage_wait', 'damage_dealt', damage_wait),
                             ('cancel', 'attack_declared', remove_weapon), ('dove_entry', 'minion_summoned', dove_entry)):
        r.register_behavior(TEST + key, body)
        r.register_card(CardDefinition(TEST + key, key, CardType.MINION, health=20,
                                       triggers=(TriggerSpec(event, TEST + key),), metadata=META))
    return r


class ParallelTrialP01CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), enemy=(), *, deck=(YETI,)*5, enemy_hand=(),
             seed=101, mana=20, maximum=20, enemy_maximum=20, temporary=0, hand_cap=None, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=mana, max_mana=maximum,
                        mana_cap=40, temporary_mana=temporary, weapon_card_id=weapon, hand_cap=hand_cap,
                        hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*5,
                        mana=enemy_maximum, max_mana=enemy_maximum, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), seed=seed), self.r)

    def entity(self, g, cid, player=1, zone='board'):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        p = g.state.active_player
        source = self.entity(g, cid, p, 'hand').id
        g.apply(PlayCard(p, source, target, len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None))
        return source

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def attack(self, g):
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            visible = json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for private in ('rng_state', 'resolution_frame', 'MinionReference', 'CardReference', 'checkpoint'):
                self.assertNotIn(private, visible)
        return restored

    def keep(self, g):
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.choose(g, 'keep')

    def test_full_raw_pins_faces_metadata_and_native_declarations(self):
        data = load_batch()
        self.assertEqual(tuple(row['record']['id'] for row in data['cards']), ROOTS)
        self.assertEqual(len(data['official_observations']['observations']), 16)
        self.assertFalse(data['dependencies'])
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])
        def normalized(s):
            return re.sub(r'\s+|<[^>]+>|\[x\]|[$&]', '', s)
        for row in data['cards']:
            raw = row['record']
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            card = self.r.card(raw['id'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=card.id))
            self.assertEqual(card.cost, raw['cost'])
            self.assertEqual(card.attack, raw['attack'] or 0)
            self.assertEqual(card.health if card.kind == CardType.MINION else card.durability if card.kind == CardType.WEAPON else None, raw['health'])
            for observation in (o for o in data['official_observations']['observations'] if o['card_id'] == card.id):
                face = observation['face']
                english = observation['locale'] == 'en-us'
                self.assertEqual(face['name'], raw['name_en' if english else 'name'])
                self.assertEqual(normalized(face['text']), normalized(raw['text_en' if english else 'text']))
                self.assertEqual(face['manaCost'], raw['cost'])
        for cid in (DAGGERS, REND):
            self.assertIn(Keyword.REWIND, self.r.card(cid).keywords)
            self.assertEqual(self.r.card(cid).rewind.retries, 1)
        self.assertEqual(self.r.card(TENDER).hand_actions[0].kind, 'trade')
        self.assertEqual(self.r.card(REND).spell_school.value, 'fel')
        self.assertEqual(self.r.card(CLAW).metadata.runes.unholy, 1)

    def test_claw_completed_hero_attack_buffs_one_friendly_minion(self):
        g = self.game((CLAW,), (YETI, TEST+'beast'), (YETI,))
        self.play(g, CLAW)
        before = [g.state.entities[i].attack for i in g.state.players[1].board]
        self.attack(g)
        self.assertEqual(sum(g.state.entities[i].attack-b for i, b in zip(g.state.players[1].board, before)), 2)
        self.assertEqual(self.entity(g, YETI, 2).attack, 4)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.portable(g)

    def test_claw_last_durability_use_keeps_original_attack_reward(self):
        g = self.game((CLAW, TEST+'last'), (YETI,))
        source = self.play(g, CLAW)
        self.play(g, TEST+'last')
        self.attack(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(self.entity(g, YETI).attack, 6)

    def test_claw_bare_combat_and_minion_attack_do_not_claim_hero_attack(self):
        g = self.game((TEST+'bare',), (YETI,), weapon=CLAW)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Bare hero combat'):
            self.play(g, TEST+'bare')
        self.assertEqual(g.snapshot(), saved)
        g.apply(Attack(1, self.entity(g, YETI).id, self.hero(g, 2).id))
        self.assertEqual(self.entity(g, YETI).attack, 4)
        self.assertEqual(len(g.state.character_attack_history), 1)

    def test_claw_removed_before_attack_completion_has_no_reward(self):
        g = self.game((CLAW,), (YETI,), (TEST+'cancel',))
        self.play(g, CLAW)
        self.attack(g)
        self.assertEqual(self.entity(g, YETI).attack, 4)

    def test_claw_empty_or_inactive_pool_does_not_consume_rng(self):
        g = self.game((CLAW,), (TEST+'sleep', TEST+'location'))
        self.play(g, CLAW)
        before = g.snapshot()['rng_state']
        self.attack(g)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_dove_draws_original_minion_and_buffs_actual_hand_only(self):
        g = self.game((DOVE, TEST+'plain', FIREBALL), deck=(FIREBALL, TEST+'beast'))
        original = self.entity(g, TEST+'beast', zone='deck').id
        source = self.play(g, DOVE)
        self.assertEqual(self.entity(g, TEST+'beast', zone='hand').id, original)
        self.assertEqual(self.entity(g, TEST+'beast', zone='hand').max_health, 5)
        self.assertEqual(self.entity(g, TEST+'plain', zone='hand').max_health, 5)
        self.assertEqual(g.state.entities[source].max_health, 2)
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_dove_no_matching_minion_or_empty_deck_skips_fatigue_but_buffs(self):
        for deck in ((), (FIREBALL,)):
            with self.subTest(deck=deck):
                g = self.game((DOVE, YETI), deck=deck)
                self.play(g, DOVE)
                self.assertEqual(self.hero(g).health, 30)
                self.assertEqual(self.entity(g, YETI, zone='hand').max_health, 7)
                self.assertEqual(len(g.state.players[1].deck), len(deck))

    def test_dove_draw_reaction_wait_and_failure_restore_before_actual_hand_buff(self):
        g = self.game((DOVE, YETI), (TEST+'draw_wait',), deck=(TEST+'plain',))
        self.play(g, DOVE)
        drawn = self.entity(g, TEST+'plain', zone='hand').id
        self.assertEqual(g.state.entities[drawn].max_health, 3)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'replace')
        self.choose(other, 'replace')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[drawn].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[drawn].max_health, 3)
        self.assertEqual(self.entity(g, TEST+'beast', zone='hand').max_health, 5)
        self.assertEqual(self.entity(g, YETI, zone='hand').max_health, 7)
        self.portable(g)

    def test_dove_burned_draw_is_not_buffed_or_replaced(self):
        g = self.game((DOVE, YETI), (TEST+'dove_entry',), deck=(TEST+'beast',), hand_cap=2)
        original = self.entity(g, TEST+'beast', zone='deck').id
        self.play(g, DOVE)
        self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertEqual(self.entity(g, TEST+'plain', zone='hand').max_health, 5)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[original].max_health, 3)
        self.assertFalse(g.state.players[1].deck)

    def test_dinomancy_buffs_friendly_beasts_and_all_in_three_zones(self):
        g = self.game((DINOMANCY, TEST+'beast', TEST+'all', YETI),
                      (TEST+'beast', TEST+'all', YETI), (TEST+'beast',),
                      deck=(TEST+'beast', TEST+'all', YETI), enemy_hand=(TEST+'beast',))
        self.play(g, DINOMANCY)
        for zone in ('hand', 'deck', 'board'):
            for cid in (TEST+'beast', TEST+'all'):
                e = self.entity(g, cid, zone=zone)
                self.assertEqual((e.attack, e.max_health), (4, 5))
            self.assertEqual(self.entity(g, YETI, zone=zone).attack, 4)
        self.assertEqual(self.entity(g, TEST+'beast', 2).attack, 2)
        self.assertEqual(self.entity(g, TEST+'beast', 2, 'hand').attack, 2)
        self.portable(g)

    def test_dinomancy_current_tribes_replace_printed_membership(self):
        g = self.game((TEST+'beastify', TEST+'unbeast', DINOMANCY), (TEST+'plain', TEST+'beast'))
        plain, beast = g.state.players[1].board
        self.play(g, TEST+'beastify', plain)
        self.play(g, TEST+'unbeast', beast)
        self.play(g, DINOMANCY)
        self.assertEqual(g.state.entities[plain].attack, 4)
        self.assertEqual(g.state.entities[beast].attack, 2)

    def test_dinomancy_unknown_tribe_rolls_back_instead_of_silent_nonmatch(self):
        g = self.game((DINOMANCY,), (TEST+'unknown',))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'):
            self.play(g, DINOMANCY)
        self.assertEqual(g.snapshot(), saved)

    def test_dinomancy_dormant_board_beast_is_excluded(self):
        g = self.game((DINOMANCY,), (TEST+'sleep',))
        self.play(g, DINOMANCY)
        self.assertEqual(self.entity(g, TEST+'sleep').max_health, 8)

    def test_stonecarver_only_damaged_other_friendly_at_own_end(self):
        g = self.game((TEST+'hurt', TEST+'hurt'), (STONECARVER, YETI, TEST+'plain'), (YETI,))
        source, target, plain = g.state.players[1].board
        self.play(g, TEST+'hurt', source)
        self.play(g, TEST+'hurt', target)
        g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (6, 6))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 3))
        self.assertEqual(g.state.entities[plain].attack, 2)
        g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[target].attack, 6)

    def test_stonecarver_healed_other_and_damaged_self_leave_empty_rng_pool(self):
        g = self.game((TEST+'hurt', TEST+'heal', TEST+'hurt'), (STONECARVER, YETI))
        source, target = g.state.players[1].board
        self.play(g, TEST+'hurt', target)
        self.play(g, TEST+'heal', target)
        self.play(g, TEST+'hurt', source)
        before = g.snapshot()['rng_state']
        g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.entities[target].attack, 4)

    def test_stonecarver_silence_removes_future_end_trigger(self):
        g = self.game((TEST+'hurt', TEST+'silence'), (STONECARVER, YETI))
        source, target = g.state.players[1].board
        self.play(g, TEST+'hurt', target)
        self.play(g, TEST+'silence', source)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[target].attack, 4)

    def test_krog_sets_all_active_enemy_stats_and_clears_damage(self):
        g = self.game((TEST+'buff', TEST+'hurt'), (KROG, YETI), (YETI, TEST+'plain', TEST+'sleep', TEST+'location'))
        target = self.entity(g, YETI, 2).id
        self.play(g, TEST+'buff', target)
        self.play(g, TEST+'hurt', target)
        g.apply(EndTurn(1))
        for cid in (YETI, TEST+'plain'):
            e = self.entity(g, cid, 2)
            self.assertEqual((e.attack, e.health, e.max_health, e.damage), (1, 1, 1, 0))
        self.assertEqual(self.entity(g, YETI).health, 5)
        self.assertEqual(self.entity(g, TEST+'sleep', 2).max_health, 8)
        self.assertEqual(self.entity(g, TEST+'location', 2).durability, 3)
        self.assertEqual(self.hero(g, 2).max_health, 30)
        self.portable(g)

    def test_krog_opponent_end_and_silence_do_not_apply(self):
        g = self.game((TEST+'silence',), (KROG,), (YETI,))
        self.play(g, TEST+'silence', self.entity(g, KROG).id)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(self.entity(g, YETI, 2).attack, 4)

    def test_krog_new_controller_end_uses_new_enemy_board(self):
        g = self.game((TEST+'control',), (KROG, YETI), (YETI,))
        self.play(g, TEST+'control', self.entity(g, KROG).id)
        g.apply(EndTurn(1))
        self.assertEqual(self.entity(g, YETI).attack, 4)
        g.apply(EndTurn(2))
        self.assertEqual(self.entity(g, YETI).attack, 1)
        self.assertEqual(self.entity(g, YETI, 2).attack, 4)

    def test_tender_gains_only_empty_permanent_difference(self):
        g = self.game((TENDER,), mana=4, maximum=4, enemy_maximum=9)
        self.play(g, TENDER)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (9, 2))
        self.assertEqual(g.state.players[2].max_mana, 9)
        self.portable(g)

    def test_tender_equal_or_ahead_does_not_destroy_crystals(self):
        for maximum, enemy in ((5, 5), (8, 5)):
            g = self.game((TENDER,), mana=maximum, maximum=maximum, enemy_maximum=enemy)
            self.play(g, TENDER)
            self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (maximum, maximum-2))

    def test_tender_temporary_available_mana_does_not_replace_crystal_comparison(self):
        g = self.game((TENDER,), mana=9, maximum=4, temporary=5, enemy_maximum=7)
        self.play(g, TENDER)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (7, 7))

    def test_tender_trade_pays_one_draws_physical_card_without_battlecry(self):
        g = self.game((TENDER,), deck=(YETI,), mana=4, maximum=4, enemy_maximum=9)
        source = self.entity(g, TENDER, zone='hand').id
        drawn = self.entity(g, YETI, zone='deck').id
        g.apply(UseHandAction(1, source, 'trade'))
        self.assertEqual(g.state.entities[source].zone, Zone.DECK)
        self.assertEqual(g.state.entities[drawn].zone, Zone.HAND)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (4, 3))
        self.assertFalse(any(e.kind == 'card_played' and e.source_id == source for e in g.events))

    def test_daggers_three_two_damage_spell_packets_with_spell_bonus(self):
        g = self.game((DAGGERS,), (TEST+'bonus',))
        source = self.play(g, DAGGERS)
        hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
        self.assertEqual(len(hits), 3)
        self.assertEqual([e.amount for e in hits], [3, 3, 3])
        self.assertEqual(self.hero(g, 2).health, 21)
        self.assertEqual(len(g.state.cast_history), 1)
        self.keep(g)
        self.assertEqual(g.state.players[1].mana, 17)

    def test_daggers_requeries_and_never_rehits_dead_enemy(self):
        g = self.game((DAGGERS,), enemy=(TEST+'tiny',), seed=0)
        target = self.entity(g, TEST+'tiny', 2).id
        source = self.play(g, DAGGERS)
        choices = [e for e in g.events if e.kind == 'random_choice' and e.source_id == source]
        self.assertEqual(len(choices), 3)
        self.assertEqual(choices[0].target_id, target)
        self.assertTrue(all(e.target_id != target for e in choices[1:]))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.keep(g)

    def test_daggers_divine_shield_absorbs_one_whole_knife(self):
        g = self.game((DAGGERS,), enemy=(TEST+'shield',), seed=0)
        source = self.play(g, DAGGERS)
        target = self.entity(g, TEST+'shield', 2)
        self.assertNotIn(Keyword.DIVINE_SHIELD, target.keywords)
        hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
        self.assertTrue(all(e.amount == 2 for e in hits))
        self.assertEqual(len([e for e in g.events if e.kind == 'random_choice' and e.source_id == source]), 3)
        self.keep(g)

    def test_daggers_waiting_packet_recovery_failure_and_rewind_portability(self):
        g = self.game((DAGGERS,), (TEST+'damage_wait',))
        self.play(g, DAGGERS)
        self.assertNotEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        for _ in range(3):
            self.choose(g)
            self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.hero(g, 2).health, 24)
        self.portable(g)
        self.keep(g)
        self.portable(g)

    def test_daggers_retry_reverts_outcome_with_one_final_payment(self):
        g = self.game((DAGGERS,), enemy=(YETI,), seed=7)
        self.play(g, DAGGERS)
        before_rng = g.snapshot()['rng_state']
        other = self.portable(g)
        self.choose(g, 'retry')
        self.choose(other, 'retry')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertNotEqual(g.snapshot()['rng_state'], before_rng)
        self.assertEqual(g.state.players[1].mana, 17)
        self.assertEqual(len(g.state.cast_history), 1)
        enemy = next(e for e in g.state.entities.values() if e.card_id == YETI and e.owner == 2 and e.zone in (Zone.BOARD, Zone.GRAVEYARD))
        self.assertEqual(30-self.hero(g, 2).health + enemy.damage, 6)
        self.portable(g)

    def test_rend_two_distinct_enemies_receive_four_plus_spell_bonus(self):
        g = self.game((REND,), (TEST+'bonus',), (YETI, TEST+'beast', TEST+'sleep'), seed=3)
        source = self.play(g, REND)
        chosen = [e.target_id for e in g.events if e.kind == 'random_choice' and e.source_id == source]
        self.assertEqual(len(chosen), 2)
        self.assertEqual(len(set(chosen)), 2)
        self.assertNotIn(self.entity(g, TEST+'sleep', 2).id, chosen)
        hits = [e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source]
        self.assertEqual([e.amount for e in hits], [5, 5])
        self.keep(g)

    def test_rend_single_enemy_gets_one_hit_without_rng_draw(self):
        g = self.game((REND,))
        before = g.snapshot()['rng_state']
        self.play(g, REND)
        self.assertEqual(self.hero(g, 2).health, 26)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.keep(g)

    def test_rend_batch_wait_retains_distinct_selection_and_resumes_before_rewind(self):
        g = self.game((REND,), (TEST+'damage_wait',), (YETI,), seed=5)
        self.play(g, REND)
        other = self.portable(g)
        for _ in range(2):
            self.choose(g)
            self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((self.hero(g, 2).health, self.entity(g, YETI, 2).health), (26, 1))
        self.portable(g)
        self.keep(g)

    def test_rend_retry_preserves_only_final_cast_payment_and_result(self):
        g = self.game((REND,), enemy=(YETI, TEST+'shield'), seed=5)
        self.play(g, REND)
        other = self.portable(g)
        self.choose(g, 'retry')
        self.choose(other, 'retry')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 16)
        self.assertEqual(len(g.state.cast_history), 1)

    def test_rewind_spells_terminal_result_does_not_offer_retry(self):
        for cid in (DAGGERS, REND):
            g = self.game((TEST+'wound_hero', cid))
            self.play(g, TEST+'wound_hero')
            self.play(g, cid)
            self.assertIsNone(g.state.pending_choice)
            self.assertEqual(g.state.winner, 1)


if __name__ == '__main__':
    unittest.main()
