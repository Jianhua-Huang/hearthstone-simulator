"""Real spell progress, old dormancy identity and original hero combat kills."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_dormant_mana_hero_kill_cards import (
    KELP, SPIRIT, load_batch, register_past_dormant_mana_hero_kill_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    CounterSpell, EndTurn, Game, Keyword, PlayerSetup, Scenario, SetSecret, SnapshotError,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.dormant_spell_mana import DormantSpellManaProfile
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, GainArmor,
    InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, DamageKind, LimitedTriggerSpec, SecretSpec
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier

P = 'k483.'
FILLER, HARD, FIGHTER, SHIELD, AXE, WATCH, SECRET = (P+x for x in
    ('filler', 'hard', 'fighter', 'shield', 'axe', 'watch', 'secret'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = defaults(); register_past_dormant_mana_hero_kill_cards(r); r._version = P+mode
    for cid, attack, health, keywords in ((FILLER, 0, 2, ()), (HARD, 0, 9, ()),
            (FIGHTER, 3, 7, ()), (SHIELD, 0, 2, (Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=5, attack=attack,
            health=health, keywords=keywords, metadata=META))
    r.register_card(CardDefinition(AXE, AXE, CardType.WEAPON, attack=3, durability=3, metadata=META))
    def fail(c): raise ResolutionError('K483 deliberate late failure')
    r.register_behavior(P+'fail', fail)
    def menu(c):
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    def five(c):
        return menu(c) if mode == 'cast_wait' else (GainArmor(c.player_id, 1),)
    def discount(c):
        held = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == P+'five')
        return (ModifyCost(held.id, CostSpec(set_to=1), c.source_id),)
    scripts = {'zero': (0, lambda c: ()), 'one': (1, lambda c: ()),
        'two': (2, lambda c: ()), 'three': (3, lambda c: ()), 'five': (5, five),
        'discount': (0, discount),
        'auto': (0, lambda c: (CastSpell(c.player_id, P+'five', c.source_id),)),
        'auto-secret': (0, lambda c: (CastSpell(c.player_id, SECRET, c.source_id),)),
        'nested': (3, lambda c: (CastSpell(c.player_id, P+'two', c.source_id),)),
        'summon-kelp': (5, lambda c: (Summon(c.player_id, KELP),)),
        'repeat': (0, lambda c: (AddSpellRepeatModifier(c.player_id, source_id=c.source_id, uses=1),)),
        'arm': (0, lambda c: (SetSecret(3-c.player_id, SECRET),)),
        'bounce': (0, lambda c: (ReturnToHand(c.target_id),)),
        'silence': (0, lambda c: (Silence(c.target_id),)),
        'dormant': (0, lambda c: (MakeDormant(c.target_id, None, c.source_id),)),
        'give': (0, lambda c: (ChangeControl(c.target_id, 3-c.player_id),)),
        'hero-ping': (0, lambda c: (Damage(c.target_id, 3, c.state.players[c.player_id].hero_id, DamageKind.EFFECT),)),
    }
    for key, (cost, body) in scripts.items():
        r.register_behavior(P+key, body)
        r.register_card(CardDefinition(P+key, key, CardType.SPELL, cost=cost, on_play=P+key,
            targeting=TargetSpec() if key in ('bounce', 'silence', 'dormant', 'give', 'hero-ping') else None,
            metadata=META))
    r.register_secret_condition(P+'counter-condition', lambda c: c.window is not None and
        c.window.kind == 'spell' and not c.window.countered and c.window.player_id != c.player_id)
    r.register_behavior(P+'counter', lambda c: (CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET, SECRET, CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET, ('card_committed',), P+'counter-condition', P+'counter'), metadata=META))
    def watch(c):
        if mode == 'before_awake':
            if c.state.entities[c.event.source_id].card_id != P+'five': return ()
            target = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == KELP)
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('cycle', 'New dormancy', (AwakenMinion(target), MakeDormant(target, None)))), c.source_id),)
        if mode == 'after_awake': return menu(c)
        if mode in ('draw_wait', 'draw_fail'):
            if c.event.player_id != c.player_id: return ()
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if mode == 'draw_fail' else menu(c)
        return ()
    r.register_behavior(WATCH, watch)
    event = 'spell_cast_finished' if mode == 'before_awake' else 'minion_awakened' if mode == 'after_awake' else 'card_drawn'
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=9, metadata=META,
        limited_triggers=(LimitedTriggerSpec(event, WATCH),)))
    r.validate(); return r


def rehash(value):
    value['events_hash'] = canonical_hash(value['events'])
    value['state_hash'] = canonical_hash({k:v for k,v in value.items() if k not in
        ('schema_version', 'events', 'events_hash', 'state_hash')})
    return value


class PastDormantManaHeroKillTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, board=(), enemy=(FILLER,), enemy_hand=(),
            deck=(FILLER,)*12, active=1, mode='normal', weapon=None, enemy_weapon=None):
        self.mode = mode
        if mode in ('before_awake', 'after_awake', 'draw_wait', 'draw_fail'): board = (WATCH, *board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=deck, mana=40, max_mana=40, mana_cap=40, weapon_card_id=weapon),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(FILLER,)*12,
                mana=40, max_mana=40, mana_cap=40, weapon_card_id=enemy_weapon)),
            active_player=active, seed=483), fixture(mode))

    def kelp(self, g): return self.entity(g, KELP, zone='board')
    def asleep(self, g, source): return g.state.entities[source].dormancy is not None
    def hero_attack(self, g, target, player=1):
        g.apply(Attack(player, g.state.players[player].hero_id, target))

    def test_complete_sources_four_faces_zero_attack_and_two_spirit_tribes(self):
        d = load_batch(); self.assertEqual((len(d['dependencies']), len(d['official_observations'])), (2, 4))
        rows = {x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']), o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'],
                numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(fixture().card(KELP).metadata.tribes, ('naga',))
        self.assertEqual(fixture().card(SPIRIT).metadata.tribes, ('undead', 'beast'))
        self.assertFalse(d['formal_pool_complete']); self.assertFalse(d['cn_calibrated'])

    def test_kelp_starts_dormant_then_original_three_and_two_awaken_with_rush(self):
        g = self.game((KELP, P+'three', P+'two')); source = self.play(g, KELP)
        self.assertTrue(self.asleep(g, source)); self.assertNotIn(Keyword.RUSH, g.state.entities[source].keywords)
        self.play(g, P+'three'); self.assertTrue(self.asleep(g, source))
        self.play(g, P+'two'); self.assertFalse(self.asleep(g, source))
        target = self.entity(g, FILLER, 2, 'board').id
        g.apply(Attack(1, source, target)); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in g.events), 1); self.portable(g)

    def test_previous_spells_do_not_count_for_later_entry(self):
        g = self.game((P+'five', KELP, P+'three', P+'two')); self.play(g, P+'five')
        source = self.play(g, KELP); self.assertEqual(g.state.entities[source].dormancy.first_cast_id, 2)
        self.play(g, P+'three'); self.assertTrue(self.asleep(g, source))
        self.play(g, P+'two'); self.assertFalse(self.asleep(g, source))

    def test_two_physical_kelpkeepers_have_independent_installation_prefixes(self):
        g = self.game((KELP, P+'three', KELP, P+'two', P+'three'))
        first = self.play(g, KELP); self.play(g, P+'three'); second = self.play(g, KELP)
        self.play(g, P+'two'); self.assertFalse(self.asleep(g, first)); self.assertTrue(self.asleep(g, second))
        self.play(g, P+'three'); self.assertFalse(self.asleep(g, second))

    def test_effective_discounted_quote_and_zero_cost_not_printed_cost(self):
        g = self.game((P+'discount', P+'five', P+'zero', P+'three', P+'one'), board=(KELP,))
        source = self.kelp(g).id; self.play(g, P+'discount'); self.play(g, P+'five'); self.play(g, P+'zero')
        self.assertTrue(self.asleep(g, source))
        row = next(x for x in g.state.cast_history if x.card_id == P+'five'); self.assertEqual(row.source_cost.amount, 1)
        self.play(g, P+'three'); self.assertTrue(self.asleep(g, source))
        self.play(g, P+'one'); self.assertFalse(self.asleep(g, source))

    def test_automatic_cast_uses_original_quote_without_manual_payment(self):
        g = self.game((P+'auto',), board=(KELP,)); source = self.kelp(g).id; mana = g.state.players[1].mana
        self.play(g, P+'auto'); self.assertFalse(self.asleep(g, source))
        row = next(x for x in g.state.cast_history if x.card_id == P+'five')
        self.assertEqual((row.origin, row.source_cost.amount), ('effect', 5))
        self.assertEqual(g.state.players[1].mana, mana); self.portable(g)

    def test_repeated_casts_count_each_original_quote_but_only_one_payment(self):
        g = self.game((P+'repeat', P+'three'), board=(KELP,)); source = self.kelp(g).id
        self.play(g, P+'repeat'); before = g.state.players[1].mana; self.play(g, P+'three')
        rows = [x for x in g.state.cast_history if x.card_id == P+'three']
        self.assertEqual([x.origin for x in rows], ['hand', 'repeat'])
        self.assertEqual([x.source_cost.amount for x in rows], [3, 3])
        self.assertEqual(g.state.players[1].mana, before-3); self.assertFalse(self.asleep(g, source))

    def test_child_completed_before_parent_is_not_lost_from_original_history(self):
        g = self.game((P+'nested',), board=(KELP,)); source = self.kelp(g).id
        self.play(g, P+'nested'); self.assertFalse(self.asleep(g, source))
        self.assertEqual([x.source_cost.amount for x in g.state.cast_history], [3, 2]); self.portable(g)

    def test_spell_summoning_source_does_not_borrow_preinstallation_acceptance(self):
        g = self.game((P+'summon-kelp', P+'five')); self.play(g, P+'summon-kelp'); source = self.kelp(g).id
        self.assertTrue(self.asleep(g, source)); self.assertEqual(g.state.entities[source].dormancy.first_cast_id, 2)
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source))

    def test_countered_paid_spell_does_not_awaken(self):
        g = self.game((P+'arm', P+'five', P+'five'), board=(KELP,)); source = self.kelp(g).id
        self.play(g, P+'arm'); self.play(g, P+'five'); self.assertTrue(self.asleep(g, source))
        row = next(x for x in g.state.cast_history if x.card_id == P+'five')
        self.assertEqual((row.failure, row.source_cost.amount), ('countered', 5))
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source))

    def test_automatic_nonordinary_secret_keeps_its_own_original_quote(self):
        g = self.game((P+'auto-secret', P+'five'), board=(KELP,)); source = self.kelp(g).id
        self.play(g, P+'auto-secret'); self.assertTrue(self.asleep(g, source))
        row = next(x for x in g.state.cast_history if x.card_id == SECRET)
        self.assertEqual((row.completed, row.source_cost.amount), (True, 0))
        self.assertEqual(len(g.state.players[1].secrets), 1)
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source)); self.portable(g)

    def test_enemy_spell_and_five_mana_minion_do_not_count(self):
        g = self.game((FIGHTER, P+'five'), board=(KELP,), enemy_hand=(P+'five',), active=2)
        source = self.kelp(g).id; self.play(g, P+'five', player=2); self.assertTrue(self.asleep(g, source))
        g.apply(EndTurn(2)); self.play(g, FIGHTER); self.assertTrue(self.asleep(g, source))
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source))

    def test_progress_spans_real_turns_without_countdown(self):
        g = self.game((P+'three', P+'two'), board=(KELP,)); source = self.kelp(g).id
        self.play(g, P+'three'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertTrue(self.asleep(g, source)); self.play(g, P+'two'); self.assertFalse(self.asleep(g, source))

    def test_pending_spell_does_not_progress_until_completion_and_restores(self):
        g = self.game((P+'five',), board=(KELP,), mode='cast_wait'); source = self.kelp(g).id
        self.play(g, P+'five'); self.assertTrue(self.asleep(g, source)); other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertFalse(self.asleep(g, source))

    def test_awakened_wait_restores_without_second_awaken_or_payment(self):
        g = self.game((P+'five',), board=(KELP,), mode='after_awake'); source = self.kelp(g).id
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source)); other = self.portable(g)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in g.events), 1)

    def test_accepted_awaken_cannot_target_new_dormancy_on_same_entity(self):
        g = self.game((P+'five', P+'five'), board=(KELP,), mode='before_awake'); source = self.kelp(g).id
        old = g.state.entities[source].dormancy.id; self.play(g, P+'five'); self.portable(g); self.choose(g, 'cycle')
        self.assertTrue(self.asleep(g, source)); self.assertNotEqual(g.state.entities[source].dormancy.id, old)
        self.assertEqual(g.state.entities[source].dormancy.first_cast_id, 2)
        self.play(g, P+'five'); self.assertFalse(self.asleep(g, source)); self.portable(g)

    def test_bounce_reentry_restarts_and_silence_does_not_restore_listener(self):
        g = self.game((P+'five', P+'bounce', P+'silence', P+'dormant', P+'five', P+'five'), board=(KELP,))
        source = self.kelp(g).id; self.play(g, P+'five'); self.play(g, P+'bounce', source); self.play(g, KELP)
        self.assertTrue(self.asleep(g, source)); self.play(g, P+'five'); self.assertFalse(self.asleep(g, source))
        self.play(g, P+'silence', source); self.play(g, P+'dormant', source)
        self.play(g, P+'five'); self.assertTrue(self.asleep(g, source)); self.assertFalse(g.state.entities[source].keywords)

    def test_future_or_boolean_dormancy_prefix_is_rejected_and_private(self):
        g = self.game(board=(KELP,)); source = self.kelp(g).id
        for value in (True, 2):
            s = deepcopy(g.snapshot()); s['state']['entities'][str(source)]['dormancy']['first_cast_id'] = value
            with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(s), fixture('normal', 'reader'))
        for pid in (1, 2):
            view = json.dumps(g.observe(pid)) + json.dumps(g.player_events(pid))
            for key in ('first_cast_id', 'source_cost', 'dormant_spell_mana_profiles'): self.assertNotIn(key, view)

    def test_spirit_draws_once_for_actual_own_hero_combat_kill(self):
        g = self.game(board=(SPIRIT,), weapon=AXE); target = self.entity(g, FILLER, 2, 'board').id
        before = len(g.state.players[1].hand); self.hero_attack(g, target)
        self.assertEqual(len(g.state.players[1].hand), before+1); self.assertEqual(len(g.state.draw_history), 1)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.portable(g)

    def test_spirit_does_not_draw_for_minion_kill_or_hero_spell_damage(self):
        g = self.game((P+'hero-ping',), board=(SPIRIT, FIGHTER), enemy=(FILLER, FILLER))
        targets = list(g.state.players[2].board); g.apply(Attack(1, self.entity(g, FIGHTER, zone='board').id, targets[0]))
        self.assertFalse(g.state.draw_history); self.play(g, P+'hero-ping', targets[1]); self.assertFalse(g.state.draw_history)

    def test_spirit_does_not_draw_for_nonlethal_or_divine_shield_or_face(self):
        for enemy in ((HARD,), (SHIELD,), ()):
            with self.subTest(enemy=enemy):
                g = self.game(board=(SPIRIT,), enemy=enemy, weapon=AXE)
                target = g.state.players[2].board[0] if enemy else g.state.players[2].hero_id
                self.hero_attack(g, target); self.assertFalse(g.state.draw_history)

    def test_enemy_hero_kill_does_not_reward_original_controller(self):
        g = self.game(board=(SPIRIT, FILLER), active=2, enemy_weapon=AXE)
        self.hero_attack(g, self.entity(g, FILLER, zone='board').id, 2); self.assertFalse(g.state.draw_history)

    def test_printed_stealth_expires_at_original_next_owner_start(self):
        g = self.game(board=(SPIRIT,)); source = self.entity(g, SPIRIT, zone='board').id
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords); g.apply(EndTurn(1))
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords); g.apply(EndTurn(2))
        self.assertNotIn(Keyword.STEALTH, g.state.entities[source].keywords); self.portable(g)

    def test_control_transfer_rewards_new_hero_and_keeps_original_stealth_deadline(self):
        g = self.game((P+'give',), board=(SPIRIT, FILLER), weapon=AXE, enemy_weapon=AXE)
        source = self.entity(g, SPIRIT, zone='board').id; expiry = next(a.keyword_expiry for a in g.state.entities[source].abilities if a.timed_keyword)
        self.play(g, P+'give', source); self.hero_attack(g, self.entity(g, FILLER, 2, 'board').id)
        self.assertFalse(g.state.draw_history); g.apply(EndTurn(1)); before = len(g.state.players[2].hand)
        self.hero_attack(g, self.entity(g, FILLER, zone='board').id, 2)
        self.assertEqual(len(g.state.players[2].hand), before+1)
        self.assertEqual(next(a.keyword_expiry for a in g.state.entities[source].abilities if a.timed_keyword), expiry)
        self.portable(g)

    def test_silenced_spirit_has_no_stealth_or_combat_reward(self):
        g = self.game((P+'silence',), board=(SPIRIT,), weapon=AXE); source = self.entity(g, SPIRIT, zone='board').id
        self.play(g, P+'silence', source); self.assertNotIn(Keyword.STEALTH, g.state.entities[source].keywords)
        self.hero_attack(g, g.state.players[2].board[0]); self.assertFalse(g.state.draw_history)

    def test_two_spirits_make_two_ordinary_draws(self):
        g = self.game(board=(SPIRIT, SPIRIT), weapon=AXE); self.hero_attack(g, g.state.players[2].board[0])
        self.assertEqual(len(g.state.draw_history), 2); self.assertEqual(len(g.state.players[1].hand), 2)

    def test_draw_choice_restores_and_failed_choice_does_not_repeat_combat(self):
        g = self.game(board=(SPIRIT,), weapon=AXE, mode='draw_wait'); self.hero_attack(g, g.state.players[2].board[0])
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(g.state.draw_history), 1)

    def test_late_draw_failure_rolls_back_whole_attack_weapon_and_death(self):
        g = self.game(board=(SPIRIT,), weapon=AXE, mode='draw_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.hero_attack(g, g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), before)

    def test_full_hand_reward_uses_real_overdraw_not_task_reward_deferral(self):
        g = self.game((FILLER,)*10, board=(SPIRIT,), weapon=AXE); self.hero_attack(g, g.state.players[2].board[0])
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(len(g.state.draw_history), 1)
        self.assertTrue(any(e.kind == 'card_burned' for e in g.events)); self.assertFalse(g.state.quest_hand_rewards)

    def test_empty_deck_reward_uses_real_fatigue(self):
        g = self.game(board=(SPIRIT,), weapon=AXE, deck=()); self.hero_attack(g, g.state.players[2].board[0])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 29)

    def test_registry_profiles_are_finite_immutable_and_default_fingerprint_unchanged(self):
        r = fixture(); self.assertEqual(r.dormant_spell_mana_profiles[KELP], DormantSpellManaProfile(KELP))
        with self.assertRaises(TypeError): r.dormant_spell_mana_profiles[KELP] = DormantSpellManaProfile(KELP)
        with self.assertRaises(ValueError): DormantSpellManaProfile(KELP, 4)
        other = defaults(); register_past_dormant_mana_hero_kill_cards(other)
        with self.assertRaises(ValueError): other.register_dormant_spell_mana_profile(DormantSpellManaProfile(KELP))
        other.freeze()
        with self.assertRaises(ValueError): other.register_dormant_spell_mana_profile(DormantSpellManaProfile(KELP))
        self.assertEqual(defaults().fingerprint(), 'b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a')
        self.assertEqual(len(build_registry().dormant_spell_mana_profiles), 1)
