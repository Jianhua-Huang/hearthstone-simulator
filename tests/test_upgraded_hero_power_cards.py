"""Real upgraded power dependencies; Genn itself is intentionally still pending."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.upgraded_hero_power_cards import DAGGER, GHOUL, POWERS, TOTEMS, UPGRADES, load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.model import DamageKind, Resource
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools.card_batch import check_face

P = 'k217a.'
WATCH, SPELLPOWER, HURT, OTHER_GHOUL = (P+x for x in ('watch', 'spellpower', 'hurt', 'other-ghoul'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def registry(mode=None):
    from hs_sim.cards import build_registry
    r = build_registry()
    r.register_behavior(P+'hurt', lambda c: (Damage(c.state.players[c.player_id].hero_id, 7, c.source_id, DamageKind.SPELL),))
    r.register_behavior(P+'other-ghoul', lambda c: (SummonByCard(3-c.player_id,
        (SummonEntryMaterial(GHOUL),), SummonCause.capture(c)),))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate upgraded power rollback')))
    for cid, body in ((HURT, P+'hurt'), (OTHER_GHOUL, P+'other-ghoul')):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=body, metadata=META))
    r.register_card(CardDefinition(SPELLPOWER, SPELLPOWER, CardType.MINION, health=10,
        spell_damage=5, metadata=META))
    def watch(c):
        if mode != 'wait' or c.event.player_id != c.player_id: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    behavior = P+'watch.'+str(mode); r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec('hero_power_started', behavior),)))
    r.validate(); return r


class UpgradedHeroPowerTests(unittest.TestCase):
    def game(self, index=1, owner=1, hand=(), board=(), enemy=(), deck=('CS2_182',)*5,
             weapon=None, mode=None):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(f'HERO_{index:02}', hero_power_card_id=POWERS[index-1],
            hand=hand, board=board, deck=deck, weapon_card_id=weapon, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=enemy,
            deck=('CS2_182',)*5, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=217), registry(mode))
    def hero(self, g, player=None):
        return g.state.entities[g.state.players[self.owner if player is None else player].hero_id]
    def power(self, g): return g.state.entities[g.state.players[self.owner].hero_power_id]
    def use(self, g, target=None): g.apply(UseHeroPower(self.owner, self.power(g).id, target))
    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def play(self, g, cid):
        eid = next(i for i in g.state.players[self.owner].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(self.owner, eid))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())
            for key in ('rng_state', 'hand_entry_id', 'hero_power_history', 'source_allocation'):
                self.assertNotIn(key, public)
        return restored

    def test_complete_twenty_nine_rows_twenty_strict_faces_and_explicit_primary_gaps(self):
        data = load_batch(); r = registry()
        self.assertEqual((len(data['cards']), len(data['dependencies']), len(data['existing_dependencies'])), (11, 2, 16))
        self.assertEqual(len(data['official_observations']), 20)
        self.assertEqual(set(data['missing_primary_ids']), {'HERO_09bp2', 'HERO_11bp2', GHOUL})
        self.assertEqual(len(UPGRADES), 11)
        for cid in POWERS: self.assertEqual(r.card(cid).kind, CardType.HERO_POWER)
        self.assertNotIn('CATA_615', r.cards); self.assertNotIn('CATA_615t', r.cards)

    def test_two_exact_display_pins_accept_both_complete_primary_languages(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['cards']}
        for observation in data['official_observations']:
            cid = observation['card_id']
            if cid in data['display_normalizations']:
                check_face(rows[cid], observation['face'], observation['locale'], data['display_normalizations'][cid])

    def test_live_slot_and_dual_body_exceptions_reject_changed_rules_ids_and_wrong_declarations(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['cards']}
        for observation in data['official_observations']:
            cid = observation['card_id']
            if cid not in data['display_normalizations']: continue
            row, face, loc = rows[cid], observation['face'], observation['locale']
            for field, value in (('id', 'another-card'), ('cost', 7), ('text_en', row['text_en']+' Extra rule.')):
                changed = deepcopy(row); changed[field] = value
                with self.assertRaises(ValueError):
                    check_face(changed, face, loc, data['display_normalizations'][cid])
            with self.assertRaises(ValueError): check_face(row, face, loc)

    def test_all_eleven_actual_manual_activations_pay_printed_cost_once_and_record_normal_history(self):
        for index in range(1, 12):
            with self.subTest(index=index):
                g = self.game(index, owner=1+index%2)
                target = self.hero(g, 3-self.owner).id if index == 8 else self.hero(g).id if index == 9 else None
                self.use(g, target)
                if index == 2: self.choose(g, TOTEMS[0])
                cost = 1 if index == 10 else 2
                self.assertEqual(g.state.players[self.owner].mana, 20-cost)
                self.assertEqual((self.power(g).uses_this_turn, len(g.state.hero_power_history)), (1, 1))
                row = g.state.hero_power_history[0]
                self.assertEqual((row.card_id, row.origin, row.cost, row.completed), (POWERS[index-1], 'manual', cost, True))
                self.assertFalse(g.state.play_history); self.assertFalse(g.state.cast_history)
                saved = g.snapshot()
                with self.assertRaises(IllegalAction): self.use(g, target)
                self.assertEqual(g.snapshot(), saved)

    def test_warrior_gains_four_armor(self):
        g = self.game(1); self.use(g)
        self.assertEqual((self.hero(g).armor, self.hero(g).health), (4, 30)); self.portable(g)

    def test_hunter_and_mage_use_hero_power_damage_without_spell_damage_bonus(self):
        for index, amount in ((5, 3), (8, 2)):
            g = self.game(index, owner=2, board=(SPELLPOWER,)); enemy = self.hero(g, 1)
            self.use(g, enemy.id if index == 8 else None)
            self.assertEqual(self.hero(g, 1).health, 30-amount); self.portable(g)

    def test_priest_restores_four_actual_missing_health(self):
        g = self.game(9, hand=(HURT,)); self.play(g, HURT); self.assertEqual(self.hero(g).health, 23)
        self.use(g, self.hero(g).id); self.assertEqual(self.hero(g).health, 27); self.portable(g)

    def test_druid_and_demon_hunter_attack_expires_but_armor_persists(self):
        for index, armor in ((6, 2), (10, 0)):
            g = self.game(index); self.use(g)
            self.assertEqual((self.hero(g).attack, self.hero(g).armor), (2, armor))
            g.apply(EndTurn(self.owner)); self.assertEqual((self.hero(g).attack, self.hero(g).armor), (0, armor))
            self.portable(g)

    def test_warlock_draw_has_no_additional_life_loss_and_empty_deck_uses_only_fatigue(self):
        for deck, health, count in ((('CS2_182',), 30, 1), ((), 29, 0)):
            g = self.game(7, deck=deck); self.use(g)
            self.assertEqual((self.hero(g).health, len(g.state.players[1].hand)), (health, count)); self.portable(g)

    def test_rogue_equips_original_two_two_weapon_retires_old_and_uses_normal_attack_wear(self):
        g = self.game(3, weapon='CS2_082'); old = g.state.players[1].weapon_id; self.use(g)
        weapon = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id, weapon.attack, weapon.durability), (DAGGER, 2, 2))
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual((self.hero(g, 2).health, g.state.entities[weapon.id].durability), (28, 1)); self.portable(g)

    def test_paladin_has_two_fixed_recruits_and_partial_capacity_keeps_only_actual_success(self):
        for board, added in (((), 2), (('CS2_182',)*6, 1)):
            g = self.game(4, board=board); before = g.snapshot()['rng_state']; self.use(g)
            recruits = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == 'CS2_101t']
            self.assertEqual(len(recruits), added)
            self.assertTrue(all((e.attack, e.health) == (1, 1) for e in recruits))
            self.assertEqual(g.snapshot()['rng_state'], before); self.portable(g)

    def test_shaman_offers_all_four_totems_even_if_same_totem_already_present_and_is_not_discover(self):
        g = self.game(2, board=(TOTEMS[0],)); self.use(g)
        q = g.state.pending_choice; self.assertEqual(tuple(x.id for x in q.options), TOTEMS)
        g = self.portable(g); self.choose(g, TOTEMS[0])
        self.assertEqual(sum(g.state.entities[i].card_id == TOTEMS[0] for i in g.state.players[1].board), 2)
        self.assertFalse(g.state.card_discovery_history); self.portable(g)

    def test_board_requiring_powers_reject_full_board_without_payment(self):
        for index in (2, 4, 11):
            g = self.game(index, board=('CS2_182',)*7); before = g.snapshot()
            with self.assertRaises(IllegalAction): self.use(g)
            self.assertEqual(g.snapshot(), before)

    def test_upgraded_ghoul_has_charge_attacks_for_two_then_dies_on_owner_end_and_grants_corpse(self):
        g = self.game(11); self.use(g); source = g.state.players[1].board[-1]; ghoul = g.state.entities[source]
        self.assertEqual((ghoul.card_id, ghoul.attack, ghoul.health), (GHOUL, 2, 1))
        g.apply(Attack(1, source, self.hero(g, 2).id)); self.assertEqual(self.hero(g, 2).health, 28)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 1); self.portable(g)

    def test_ghoul_owner_end_policy_does_not_die_on_other_players_end(self):
        g = self.game(8, hand=(OTHER_GHOUL,)); self.play(g, OTHER_GHOUL)
        source = g.state.players[2].board[-1]; g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD); g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.portable(g)

    def test_started_power_wait_preserves_paid_target_and_failed_choice_is_atomic(self):
        g = self.game(8, board=(WATCH,), mode='wait'); self.use(g, self.hero(g, 2).id)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.hero(g, 2).health, 30)
        self.assertEqual(g.state.players[1].mana, 18); g = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'ok')
        self.assertEqual(self.hero(g, 2).health, 28); self.portable(g)

    def test_mage_target_admission_rejects_hand_card_and_preserves_payment(self):
        g = self.game(8, hand=('CS2_182',)); target = g.state.players[1].hand[0]; saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g, target)
        self.assertEqual(g.snapshot(), saved); self.portable(g)
