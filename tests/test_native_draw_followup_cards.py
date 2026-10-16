"""Original physical tutors, prepared Kindred and finite future hero grants."""
from dataclasses import asdict
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_draw_followup_cards import (
    CHRONIKAR, CINDER, DREAMWARDEN, PREFIX, ROOTS, SLAGCLAW, VANGUARD, load_batch,
)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy,
    DeckSpec, EndTurn, Game, Keyword, MatchSetup, OpeningHook, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChangeManaCrystals,
    ChoiceOption, Damage, Destroy, Draw, GainArmor, InvokeBehavior, ReplaceHero,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.model import BattlecryRepeatSpec, DamageKind, PlayerEffectSpec, Rarity
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.targets import canonical_digest

YETI = 'CORE_CS2_182'


def registry():
    r = build_registry()
    meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())

    def original(c, player=1):
        ids = set(c.state.opening.original_entities[player-1])
        return next(c.state.entities[i] for i in c.state.players[player].deck
                    if i in ids and c.state.entities[i].card_id == YETI)

    def boot(c):
        return (ChangeManaCrystals(c.player_id, 10, filled=True),
            *(AddToHand(c.player_id, cid, c.source_id) for cid in
              (DREAMWARDEN, 'k86.add', 'k86.transform', 'k86.foreign', 'k86.watch', 'k86.fill')))

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in (DREAMWARDEN, VANGUARD):
            return ()
        ref = CardReference.capture(c.state.entities[c.event.target_id])
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('bounce', 'Return the source', (ReturnToHand(source.id),)),
            ChoiceOption('cycle', 'Redraw the same object', (
                MoveCard(ref, c.player_id, Zone.DECK, 'top', source_id=c.source_id),
                Draw(c.player_id, source_id=c.source_id))),
            ChoiceOption('bad', 'Fail atomically', (InvokeBehavior('k86.fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    def wait_start(c):
        if c.event.player_id != c.player_id or c.state.entities[c.state.players[c.player_id].hero_id].armor:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('bad', 'Fail', (InvokeBehavior('k86.fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    scripts = {
        'add': lambda c: (AddToDeck(c.player_id, YETI, 'bottom', c.source_id),),
        'transform': lambda c: (TransformStoredCard(CardReference.capture(original(c, c.player_id)), YETI, c.source_id),),
        'foreign': lambda c: (MoveCard(CardReference.capture(original(c, 3-c.player_id)), c.player_id, Zone.DECK, source_id=c.source_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'take': lambda c: (ChangeControl(c.target_id, 2),),
        'replace': lambda c: (ReplaceHero(c.player_id, 'k86.hero', hero_power_card_id='HERO_08bp'),),
        'extra': lambda c: (QueueTurns((c.player_id,), c.source_id),),
        'capacity': lambda c: tuple(AddPlayerEffect(c.player_id, 'k86.objective', c.source_id) for _ in range(5)),
    }
    for name, body in scripts.items():
        key = 'k86.' + name
        r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.SPELL, metadata=meta, on_play=key,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name in ('kill', 'silence', 'take') else None))
    r.register_behavior('k86.fail', lambda c: (AddToHand(c.player_id, 'unknown.k86'),))
    r.register_behavior('k86.boot', boot)
    r.register_card(CardDefinition('k86.boot', 'Opening fixture', CardType.MINION, health=1,
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()),
        opening_hooks=(OpeningHook('after_mulligan', 'k86.boot'),)))
    r.register_behavior('k86.watch', watch)
    r.register_card(CardDefinition('k86.watch', 'Draw reaction', CardType.MINION, health=8, metadata=meta,
        triggers=(TriggerSpec('card_drawn', 'k86.watch'),)))
    r.register_behavior('k86.fill', lambda c: tuple(AddToHand(c.player_id, YETI, c.source_id) for _ in range(10))
        if c.state.entities[c.event.source_id].card_id in (DREAMWARDEN, VANGUARD) else ())
    r.register_card(CardDefinition('k86.fill', 'Fill before tutor', CardType.MINION, health=8, metadata=meta,
        triggers=(TriggerSpec('card_committed', 'k86.fill'),)))
    r.register_behavior('k86.start', wait_start)
    r.register_card(CardDefinition('k86.start', 'Waiting turn start', CardType.MINION, health=8, metadata=meta,
        triggers=(TriggerSpec('turn_started', 'k86.start'),)))
    r.register_card(CardDefinition('k86.brann', 'Battlecry repeat fixture', CardType.MINION, health=8, metadata=meta,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    r.register_card(CardDefinition('k86.hero', 'Replacement hero', CardType.HERO, health=30, metadata=meta))
    r.register_player_effect(PlayerEffectSpec('k86.objective', CHRONIKAR, kind='objective', duration=3, tick_event='turn_ended'))
    return r


class NativeDrawFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), *, deck=(YETI,)*8, board=(), enemy=(), seed=86):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck, board=board, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,)*12, mana=40, max_mana=40, mana_cap=40),
        ), seed=seed), self.r)

    def match(self):
        cards = ('k86.boot',) + (YETI,)*11
        policy = DeckPolicy('k86.original', 'k86.fixed', 'experimental', ('k86.boot', YETI), deck_size=12, max_copies=12)
        g = Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, cards) for _ in (1, 2)),
            policy, 'GAME_005', seed=944, first_player=1), self.r)
        while g.state.pending_choice:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        return g

    def play(self, g, cid, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target, len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None))
        return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def round(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())
            for name in ('rng_state', 'original_entities', 'starting_hands', 'pending_frame'):
                self.assertNotIn(name, public)
        return other

    def test_full_pins_real_tribes_and_existing_cinder_are_preserved(self):
        data = load_batch()
        self.assertEqual(tuple(x['record']['id'] for x in data['cards']), ROOTS)
        self.assertEqual(self.r.card(SLAGCLAW).metadata.tribes, ('elemental', 'dragon'))
        self.assertEqual(self.r.card(CHRONIKAR).metadata.classes, (CardClass.DEMON_HUNTER,))
        self.assertEqual(canonical_digest(asdict(self.r.card(CINDER))), data['existing_dependencies'][0]['definition_sha256'])
        self.assertNotIn('END_006e', self.r.cards)

    def test_dreamwarden_requires_real_starting_deck_identity_atomically(self):
        g = self.game((DREAMWARDEN,)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, DREAMWARDEN)
        self.assertEqual(g.snapshot(), before)

    def test_dreamwarden_original_only_deck_does_not_draw_or_use_rng(self):
        g = self.match(); before = g.snapshot()['rng_state']; draws = len(g.state.draw_history)
        source = self.play(g, DREAMWARDEN)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (3, 4))
        self.assertEqual(len(g.state.draw_history), draws)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_dreamwarden_same_face_new_entity_is_not_an_original(self):
        g = self.match(); self.play(g, 'k86.add')
        originals = set(g.state.opening.original_entities[0])
        generated, = [i for i in g.state.players[1].deck if i not in originals]
        source = self.play(g, DREAMWARDEN)
        self.assertEqual(g.state.draw_history[-1].entity_id, generated)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (5, 6))
        self.portable(g)

    def test_dreamwarden_explicit_face_replacement_loses_original_credit(self):
        g = self.match(); self.play(g, 'k86.transform')
        replaced, = [i for i in g.state.players[1].deck if g.state.entities[i].face_replaced]
        self.play(g, DREAMWARDEN)
        self.assertEqual(g.state.draw_history[-1].entity_id, replaced)

    def test_dreamwarden_foreign_starting_entity_is_not_my_original(self):
        g = self.match(); self.play(g, 'k86.foreign')
        foreign, = [i for i in g.state.players[1].deck if i in g.state.opening.original_entities[1]]
        self.play(g, DREAMWARDEN)
        self.assertEqual(g.state.draw_history[-1].entity_id, foreign)

    def test_dreamwarden_draw_wait_failure_and_source_return_preserve_residence(self):
        g = self.match(); self.play(g, 'k86.watch'); self.play(g, 'k86.add')
        source = self.play(g, DREAMWARDEN)
        self.assertEqual(g.state.entities[source].attack, 3)
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g, 'bounce'); self.choose(other, 'bounce')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[source].zone, Zone.HAND)
        self.assertEqual(g.state.entities[source].attack, 3)

    def test_dreamwarden_satisfied_condition_rewards_source_even_if_draw_burns(self):
        g = self.match(); self.play(g, 'k86.fill'); self.play(g, 'k86.add')
        source = self.play(g, DREAMWARDEN)
        row = next(x for x in reversed(g.state.draw_history) if x.source_id == source)
        self.assertEqual(row.outcome, 'burned')
        self.assertEqual(g.state.entities[source].attack, 5)

    def test_vanguard_original_physical_minion_receives_one_two_two_buff(self):
        g = self.game((VANGUARD,), deck=(YETI,))
        original = g.state.players[1].deck[0]; self.play(g, VANGUARD)
        entity = g.state.entities[original]
        self.assertEqual((entity.zone, entity.attack, entity.max_health), (Zone.HAND, 6, 7))
        self.choose(g, 'keep'); self.portable(g)

    def test_vanguard_empty_match_skips_fatigue_and_preserves_rng(self):
        g = self.game((VANGUARD,), deck=()); before = g.snapshot()['rng_state']
        self.play(g, VANGUARD)
        self.assertEqual(g.state.players[1].fatigue, 0)
        self.assertEqual(g.state.draw_history, [])
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.choose(g, 'keep')

    def test_vanguard_full_hand_burn_is_not_a_reward_recipient(self):
        g = self.game((VANGUARD,) + (YETI,)*9, deck=(YETI,), board=('k86.fill',))
        original = g.state.players[1].deck[0]; self.play(g, VANGUARD)
        self.assertEqual(g.state.draw_history[-1].outcome, 'burned')
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertTrue(all(g.state.entities[i].attack == 4 for i in g.state.players[1].hand))
        self.choose(g, 'keep')

    def test_vanguard_wait_restores_before_reward_and_hides_opponent_material(self):
        g = self.game((VANGUARD,), deck=(YETI,), board=('k86.watch',))
        original = g.state.players[1].deck[0]; self.play(g, VANGUARD)
        self.assertEqual(g.state.entities[original].attack, 4)
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[original].attack, 6)
        self.choose(g, 'keep'); self.portable(g)

    def test_vanguard_departed_and_redrawn_same_entity_is_not_rebound(self):
        g = self.game((VANGUARD,), deck=(YETI,), board=('k86.watch',))
        original = g.state.players[1].deck[0]; self.play(g, VANGUARD)
        self.choose(g, 'cycle')
        self.assertEqual(g.state.entities[original].zone, Zone.HAND)
        self.assertEqual(g.state.entities[original].attack, 4)
        self.choose(g, 'keep')

    def test_vanguard_real_battlecry_repeat_draws_two_originals_once_each(self):
        g = self.game((VANGUARD,), deck=(YETI, YETI), board=('k86.brann',))
        original = set(g.state.players[1].deck); source = self.play(g, VANGUARD)
        self.assertEqual({x.entity_id for x in g.state.draw_history if x.source_id == source}, original)
        self.assertTrue(all(g.state.entities[i].attack == 6 for i in original))
        self.assertEqual(g.state.players[1].mana, 37)
        self.choose(g, 'keep')

    def test_vanguard_retry_reverts_original_reward_and_pays_only_once(self):
        g = self.game((VANGUARD,), deck=(YETI,))
        original = g.state.players[1].deck[0]; source = self.play(g, VANGUARD)
        self.portable(g); self.choose(g, 'retry')
        self.assertEqual(g.state.entities[original].attack, 6)
        self.assertEqual(g.state.players[1].mana, 37)
        self.assertEqual(sum(g.state.entities[i].card_id == VANGUARD for i in g.state.players[1].board), 1)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_slagclaw_first_turn_only_summons_two_complete_cinders(self):
        g = self.game((SLAGCLAW,)); self.play(g, SLAGCLAW)
        cinders = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CINDER]
        self.assertEqual(len(cinders), 2)
        self.assertTrue(all((e.attack, e.health) == (2, 1) for e in cinders))
        self.assertEqual(self.hero(g, 2).health, 30)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare',))

    def test_slagclaw_same_turn_elemental_does_not_activate_kindred(self):
        g = self.game((CINDER, SLAGCLAW)); self.play(g, CINDER); self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 30)

    def test_slagclaw_previous_elemental_triggers_old_and_new_cinders_without_killing_them(self):
        g = self.game((CINDER, SLAGCLAW)); self.play(g, CINDER); self.round(g)
        source = self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 24)
        self.assertEqual(len(g.state.players[1].board), 4)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare', 'active'))
        self.assertEqual(len(g.state.deathrattle_history), 3)
        self.portable(g)

    def test_slagclaw_previous_dragon_also_activates_its_full_dual_type(self):
        g = self.game(('EDR_889', SLAGCLAW)); self.play(g, 'EDR_889'); self.round(g)
        self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 26)

    def test_slagclaw_previous_typeless_minion_does_not_activate_kindred(self):
        g = self.game((YETI, SLAGCLAW)); self.play(g, YETI); self.round(g)
        self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 30)

    def test_slagclaw_silenced_old_cinder_has_no_triggered_deathrattle(self):
        g = self.game((CINDER, SLAGCLAW, 'k86.silence'))
        old = self.play(g, CINDER); self.round(g); self.play(g, 'k86.silence', old)
        self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 26)

    def test_slagclaw_actual_next_kindred_source_repeats_only_bonus_not_summon_prepare(self):
        g = self.game((CINDER, SLAGCLAW, 'TLC_251')); self.play(g, CINDER); self.round(g)
        self.play(g, 'TLC_251'); self.play(g, SLAGCLAW)
        self.assertEqual(self.hero(g, 2).health, 18)
        self.assertEqual(sum(g.state.entities[i].card_id == CINDER for i in g.state.players[1].board), 3)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare', 'active', 'active'))

    def test_slagclaw_full_board_keeps_existing_cinder_and_no_phantom_summons(self):
        g = self.game((CINDER, SLAGCLAW), board=(YETI,)*4)
        self.play(g, CINDER); self.round(g); self.play(g, SLAGCLAW)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id == CINDER for i in g.state.players[1].board), 2)
        self.assertEqual(self.hero(g, 2).health, 26)

    def test_chronikar_three_owner_turns_do_not_leave_attack_on_opponent_turn(self):
        g = self.game((CHRONIKAR,)); self.play(g, CHRONIKAR)
        self.assertEqual(self.hero(g).attack, 3)
        for remaining in (1, 0):
            g.apply(EndTurn(1)); self.assertEqual(self.hero(g).attack, 0)
            g.apply(EndTurn(2)); self.assertEqual(self.hero(g).attack, 3)
            self.assertEqual(sum(x.spec_id.startswith(PREFIX) for x in g.state.players[1].player_effects), remaining)
        self.round(g)
        self.assertEqual(self.hero(g).attack, 0)
        self.portable(g)

    def test_chronikar_source_death_does_not_cancel_future_grants(self):
        g = self.game((CHRONIKAR, 'k86.kill')); source = self.play(g, CHRONIKAR)
        self.play(g, 'k86.kill', source); self.round(g)
        self.assertEqual(self.hero(g).attack, 3)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_chronikar_source_silence_does_not_remove_already_accepted_player_effect(self):
        g = self.game((CHRONIKAR, 'k86.silence')); source = self.play(g, CHRONIKAR)
        self.play(g, 'k86.silence', source); self.round(g)
        self.assertEqual(self.hero(g).attack, 3)

    def test_chronikar_source_control_change_keeps_original_player_beneficiary(self):
        g = self.game((CHRONIKAR, 'k86.take')); source = self.play(g, CHRONIKAR)
        self.play(g, 'k86.take', source); g.apply(EndTurn(1))
        self.assertEqual(self.hero(g, 2).attack, 0)
        g.apply(EndTurn(2)); self.assertEqual(self.hero(g).attack, 3)

    def test_chronikar_repeated_battlecry_keeps_independent_finite_instances(self):
        g = self.game((CHRONIKAR,), board=('k86.brann',)); self.play(g, CHRONIKAR)
        self.assertEqual(self.hero(g).attack, 6)
        self.round(g); self.assertEqual(self.hero(g).attack, 6)
        self.round(g); self.assertEqual(self.hero(g).attack, 6)
        self.round(g); self.assertEqual(self.hero(g).attack, 0)

    def test_chronikar_future_grant_uses_current_replacement_hero(self):
        g = self.game((CHRONIKAR, 'k86.replace')); self.play(g, CHRONIKAR)
        self.play(g, 'k86.replace'); self.round(g)
        self.assertEqual(self.hero(g).card_id, 'k86.hero')
        self.assertEqual(self.hero(g).attack, 3)

    def test_chronikar_actual_extra_owner_turn_consumes_one_future_stage(self):
        g = self.game((CHRONIKAR, 'k86.extra', 'k86.extra')); self.play(g, CHRONIKAR)
        for _ in range(2):
            self.play(g, 'k86.extra'); g.apply(EndTurn(1))
            self.assertEqual(g.state.active_player, 1)
            self.assertEqual(self.hero(g).attack, 3)
        g.apply(EndTurn(1)); self.assertEqual(self.hero(g).attack, 0)
        self.assertFalse(any(x.spec_id.startswith(PREFIX) for x in g.state.players[1].player_effects))

    def test_chronikar_does_not_borrow_full_objective_area_capacity(self):
        g = self.game(('k86.capacity', CHRONIKAR)); self.play(g, 'k86.capacity')
        self.play(g, CHRONIKAR)
        self.assertEqual(len(g.state.players[1].player_effects), 6)
        self.round(g); self.assertEqual(self.hero(g).attack, 3)

    def test_chronikar_start_wait_restore_failure_and_future_retirement(self):
        g = self.game((CHRONIKAR,), board=('k86.start',)); self.play(g, CHRONIKAR)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.hero(g).attack, 3)
        self.round(g); self.assertEqual(self.hero(g).attack, 3)
        self.round(g); self.assertEqual(self.hero(g).attack, 0)
        self.portable(g)
