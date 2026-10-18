"""Real Treant identity, historical deaths and original summon recipients."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.dead_treant_summon_card import (
    SPELL, TREANT, load_batch, register_dead_treant_summon_card)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_held_mana_cards import register_native_held_mana_cards
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SummonQuantitySpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, DestroyBatch,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.model import SpellSchool, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest

P = 'k206.'
HERO, BODY, WATCH, POWER, QUANTITY, IMPOSTOR, ALL = (
    P+x for x in ('hero', 'body', 'watch', 'power', 'quantity', 'impostor', 'all'))
NAMED = 'CATA_131'
OLD = 'EX1_tk9'


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+str(mode))
    data = load_batch()
    row = data['existing_dependencies'][0]['record']
    token = CardDefinition(TREANT, row['name'], CardType.MINION, cost=row['cost'],
                           attack=row['attack'], health=row['health'], metadata=metadata_from_record(row))
    r.register_card(token); r.register_pool_card(PoolCard.from_definition(token))
    register_native_held_mana_cards(r)
    register_dead_treant_summon_card(r)
    raw = next(x['record'] for x in data['evidence_only'] if x['record']['id'] == OLD)
    assert raw['text'] == '' and raw['tags']['2831'] == 1
    r.register_card(CardDefinition(OLD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw)))
    for card in (
        CardDefinition(HERO, HERO, CardType.HERO, health=60),
        CardDefinition(BODY, BODY, CardType.MINION, health=8),
        CardDefinition(POWER, POWER, CardType.MINION, health=20, spell_damage=3),
        CardDefinition(QUANTITY, QUANTITY, CardType.MINION, health=20,
                       summon_quantities=(SummonQuantitySpec(),)),
        CardDefinition(IMPOSTOR, '树人', CardType.MINION, health=2),
        CardDefinition(ALL, 'All tribes', CardType.MINION, health=2,
                       metadata=replace(token.metadata, tribes=('all',))),
    ): r.register_card(card)
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K206 deliberate failure')))
    r.register_behavior(P+'reenter', lambda c: (SummonStoredCard(
        CardReference.capture(c.state.entities[c.target_id]), c.player_id),))

    def watch(c):
        e = c.state.entities.get(c.event.target_id)
        if e is None or e.card_id != TREANT:
            return ()
        cast = next((x for x in reversed(c.state.cast_history)
                     if x.card_id == SPELL and not x.completed and not x.interrupted), None)
        if cast is None:
            return ()
        entries = [x for x in c.state.successful_summon_history if x.card_id == TREANT]
        if mode == 'nested':
            return (Summon(c.player_id, TREANT, c.source_id),) if len(entries) == 1 else ()
        if mode == 'late_fail':
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if len(entries) == 2 else ()
        options = (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ChoiceOption('kill', 'Destroy this recipient', (Destroy(e.id, c.source_id),)),
            ChoiceOption('cycle', 'Return and reenter', (ReturnToHand(e.id),
                InvokeBehavior(P+'reenter', c.source_id, c.player_id, e.id))),
            ChoiceOption('give', 'Change controller', (ChangeControl(e.id, 3-c.player_id),)),
            ChoiceOption('transform', 'Transform same residence', (Transform(e.id, BODY),)),
        )
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'watch', watch)
    events = () if mode is None else ('minion_summoned', 'stats_changed') if mode == 'all_wait' else ('minion_summoned',)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
                                  triggers=tuple(TriggerSpec(e, P+'watch') for e in events)))
    scripts = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        killall=lambda c: (DestroyBatch(tuple(i for p in c.state.players.values() for i in p.board
            if c.state.entities[i].kind == CardType.MINION), c.source_id),),
        silence_kill=lambda c: (Silence(c.target_id), Destroy(c.target_id, c.source_id)),
        transform_out=lambda c: (Transform(c.target_id, BODY), Destroy(c.target_id, c.source_id)),
        transform_in=lambda c: (Transform(c.target_id, TREANT), Destroy(c.target_id, c.source_id)),
        steal=lambda c: (ChangeControl(c.target_id, c.player_id), Destroy(c.target_id, c.source_id)),
        give=lambda c: (ChangeControl(c.target_id, 3-c.player_id), Destroy(c.target_id, c.source_id)),
        discard=lambda c: (DiscardCard(CardReference.capture(c.state.entities[c.target_id]), c.source_id),),
        auto=lambda c: (CastSpell(c.player_id, SPELL, c.source_id),),
    )
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        fields = {} if name in ('killall', 'auto') else dict(targeting=TargetSpec(
            zones=(Zone.HAND,) if name == 'discard' else (Zone.BOARD,), kinds=(CardType.MINION,)))
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, **fields))
    r.validate()
    return r


class DeadTreantSummonTests(unittest.TestCase):
    def game(self, hand=(SPELL,), board=(), enemy=(), actor=1, mode=None):
        self.mode = mode
        own = PlayerSetup(HERO, hand=hand, board=board, mana=60, max_mana=60, mana_cap=60)
        other = PlayerSetup(HERO, board=enemy, mana=60, max_mana=60, mana_cap=60)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=206), registry(mode))

    def eid(self, g, cid, zone='hand', player=None):
        player = g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid=SPELL, target=None):
        eid = self.eid(g, cid)
        g.apply(PlayCard(g.state.active_player, eid, target))
        return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def finish(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def trees(self, g, player=None):
        player = g.state.active_player if player is None else player
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == TREANT]

    def stats(self, g, player=None):
        return [(e.attack, e.max_health) for e in self.trees(g, player)]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        fresh = registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(saved), fresh).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fresh).snapshot(), saved)
        return Game.from_snapshot(deepcopy(saved), fresh)

    def prior_death(self, **kwargs):
        g = self.game(hand=(P+'kill', SPELL), board=(OLD, *kwargs.pop('board', ())), **kwargs)
        self.play(g, P+'kill', self.eid(g, OLD, 'board'))
        return g

    def test_real_face_family_and_existing_token_are_preserved(self):
        from hs_sim.cards import build_registry
        r = build_registry(); data = load_batch()
        card = r.card(SPELL)
        self.assertEqual((card.name, card.cost, card.spell_school), ('破碎现实', 4, SpellSchool.NATURE))
        self.assertEqual(card.metadata.classes[0].value, 'druid')
        self.assertEqual(len(data['treant_family']['card_ids']), 29)
        self.assertIn(NAMED, data['treant_family']['card_ids'])
        self.assertEqual(canonical_digest(asdict(r.card(TREANT))), canonical_digest(asdict(registry().card(TREANT))))
        self.assertNotIn('END_009e', r.cards)
        self.assertNotIn('DAL_256t2', r.cards)

    def test_zero_deaths_two_base_bodies_and_single_four_mana_payment(self):
        g = self.game()
        self.play(g)
        self.assertEqual(self.stats(g), [(2, 2)]*2)
        self.assertEqual(g.state.players[1].mana, 56)
        self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertFalse(g.state.death_history)

    def test_named_and_different_tokens_count_each_real_friendly_death(self):
        g = self.game(hand=(P+'killall', SPELL), board=(NAMED, OLD, OLD), enemy=(OLD,))
        self.play(g, P+'killall'); self.play(g)
        self.assertEqual(self.stats(g), [(5, 5)]*2)

    def test_names_all_tribes_and_hand_discards_are_not_treant_deaths(self):
        g = self.game(hand=(P+'killall', P+'discard', TREANT, SPELL), board=(IMPOSTOR, ALL))
        self.play(g, P+'killall')
        self.play(g, P+'discard', self.eid(g, TREANT))
        self.play(g)
        self.assertEqual(self.stats(g), [(2, 2)]*2)

    def test_silence_preserves_face_but_transformation_changes_death_identity(self):
        for script, body, want in ((P+'silence_kill', OLD, 3), (P+'transform_out', OLD, 2),
                                   (P+'transform_in', BODY, 3)):
            with self.subTest(script=script):
                g = self.game(hand=(script, SPELL), board=(body,))
                self.play(g, script, self.eid(g, body, 'board')); self.play(g)
                self.assertEqual(self.stats(g), [(want, want)]*2)

    def test_controller_at_death_and_second_seat(self):
        for actor in (1, 2):
            for script, board, enemy, want in ((P+'steal', (), (OLD,), 3), (P+'give', (OLD,), (), 2)):
                with self.subTest(actor=actor, script=script):
                    g = self.game(hand=(script, SPELL), board=board, enemy=enemy, actor=actor)
                    target = self.eid(g, OLD, 'board', 3-actor if enemy else actor)
                    self.play(g, script, target); self.play(g)
                    self.assertEqual(self.stats(g), [(want, want)]*2)

    def test_partial_and_full_board_only_reward_actual_new_entries(self):
        for bodies, want in ((5, 2), (6, 1), (7, 0)):
            with self.subTest(bodies=bodies):
                if bodies == 7:
                    g = self.game(board=(BODY,)*7)
                else:
                    g = self.prior_death(board=(BODY,)*bodies)
                self.play(g)
                self.assertEqual(self.stats(g), [(3, 3)]*want)
                self.assertEqual(len(g.state.card_summon_history), 2)

    def test_spell_damage_does_not_scale_stat_bonus(self):
        g = self.prior_death(board=(POWER,))
        self.play(g)
        self.assertEqual(self.stats(g), [(3, 3)]*2)

    def test_existing_same_token_and_nested_summon_are_not_rewarded(self):
        g = self.prior_death(board=(WATCH,), mode='nested')
        self.play(g)
        self.assertEqual(sorted(self.stats(g)), [(2, 2), (3, 3), (3, 3)])
        g = self.prior_death(board=(TREANT,))
        old = self.eid(g, TREANT, 'board'); self.play(g)
        self.assertEqual((g.state.entities[old].attack, g.state.entities[old].max_health), (2, 2))

    def test_quantity_changes_delivery_count_without_extra_payment(self):
        g = self.prior_death(board=(QUANTITY,))
        self.play(g)
        self.assertEqual(self.stats(g), [(3, 3)]*4)
        self.assertEqual(g.state.players[1].mana, 56)
        self.assertEqual(len(g.state.card_summon_history), 2)

    def test_automatic_cast_uses_same_original_group(self):
        g = self.game(hand=(P+'kill', P+'auto'), board=(OLD,))
        self.play(g, P+'kill', self.eid(g, OLD, 'board')); self.play(g, P+'auto')
        self.assertEqual(self.stats(g), [(3, 3)]*2)
        self.assertEqual(g.state.players[1].mana, 60)

    def test_repeated_casts_do_not_rebuff_the_first_group(self):
        g = self.game(hand=(P+'kill', SPELL, SPELL), board=(OLD,))
        self.play(g, P+'kill', self.eid(g, OLD, 'board'))
        self.play(g); self.play(g)
        self.assertEqual(self.stats(g), [(3, 3)]*4)
        self.assertEqual(g.state.players[1].mana, 52)

    def test_both_bodies_exist_before_group_bonus_and_each_wait_is_portable(self):
        g = self.prior_death(board=(WATCH,), mode='all_wait')
        self.play(g); waits = 0
        while g.state.pending_choice is not None:
            if waits == 1:
                self.assertEqual(self.stats(g), [(2, 2)]*2)
            other = self.portable(g)
            self.choose(g); self.choose(other)
            self.assertEqual(g.snapshot(), other.snapshot()); waits += 1
        self.assertEqual(waits, 4)
        self.assertEqual(self.stats(g), [(3, 3)]*2)

    def test_death_during_summons_is_included_in_later_group_bonus(self):
        g = self.game(board=(WATCH,), mode='summon_wait')
        self.play(g); self.choose(g, 'kill'); self.finish(g)
        self.assertEqual(self.stats(g), [(3, 3)])

    def test_bonus_amount_is_frozen_before_first_bonus_notification(self):
        g = self.prior_death(board=(WATCH,), mode='all_wait')
        self.play(g); self.choose(g); self.choose(g)
        self.assertEqual(self.stats(g), [(3, 3), (2, 2)])
        self.choose(g, 'kill'); self.finish(g)
        self.assertEqual(self.stats(g), [(3, 3)])
        self.assertEqual(len(g.state.death_history), 2)

    def test_return_and_reentry_cannot_rebind_old_successful_presence(self):
        g = self.prior_death(board=(WATCH,), mode='summon_wait')
        self.play(g); self.choose(g, 'cycle'); self.finish(g)
        self.assertEqual(sorted(self.stats(g)), [(2, 2), (3, 3)])

    def test_control_transfer_keeps_original_recipient_and_transform_keeps_residence(self):
        g = self.prior_death(board=(WATCH,), mode='summon_wait')
        self.play(g); self.choose(g, 'give'); self.finish(g)
        self.assertEqual(self.stats(g, 1), [(3, 3)])
        self.assertEqual(self.stats(g, 2), [(3, 3)])
        g = self.prior_death(board=(WATCH,), mode='summon_wait')
        self.play(g); target = self.trees(g)[0].id
        self.choose(g, 'transform'); self.finish(g)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (1, 9))

    def test_failed_selection_and_failed_full_action_preserve_transaction(self):
        g = self.prior_death(board=(WATCH,), mode='summon_wait')
        self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        g = self.prior_death(board=(WATCH,), mode='late_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_player_output_excludes_private_histories_and_runtime_context(self):
        g = self.prior_death(board=(WATCH,), mode='summon_wait'); self.play(g)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())
            for key in ('card_summon_history', 'successful_summon_history', 'death_history',
                        'RuleContext', 'resolution_frame', 'rng_state'):
                self.assertNotIn(key, public)


if __name__ == '__main__':
    unittest.main()
