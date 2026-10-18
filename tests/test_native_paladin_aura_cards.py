"""Native Aura ownership, real opponent boundaries and ordinary cost receipts."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_paladin_aura_cards import RESISTANCE, TIMEWAYS, SPEC, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerEffectSpec, PlayerSetup, Ruleset, Scenario,
    SelectChoice, SnapshotError)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec, CostSpec, LimitedTriggerSpec, SpellRepeatSpec
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P = 'k132.test.'
FIREBALL, YETI, SQUIRE = 'CORE_CS2_029', 'CORE_CS2_182', 'CORE_EX1_008'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(mode=None):
    r = build_registry()
    legacy=P+'legacy_objective'
    r.register_player_effect(PlayerEffectSpec(legacy,legacy,kind='objective',duration=3,tick_event='turn_ended'))
    r.register_card(CardDefinition(legacy,'Non-Aura objective fixture',CardType.SPELL,
        ongoing_effect_id=legacy,metadata=META))
    def fail(c):
        raise ResolutionError('K132 deliberate suspended action failure')
    def remove(c):
        e = next(e for e in c.state.players[1].player_effects if e.spec_id == SPEC)
        return (RemovePlayerEffect(1, e.id),)
    scripts = {'fail': fail, 'remove': remove,
        'tax_set': lambda c: (AddCostModifier(2, CostSpec(set_to=0, card_types=(CardType.SPELL,)), source_id=c.source_id),),
        'summon': lambda c: (Summon(1, TIMEWAYS),)}
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, metadata=META, on_play=P+name))
    r.register_card(CardDefinition(P+'repeat', 'Ordinary native spell repeat', CardType.MINION, health=9, metadata=META,
        spell_repeats=(SpellRepeatSpec(2, class_mode='any'),)))
    r.register_card(CardDefinition(P+'bc_repeat', 'Ordinary Battlecry repeat', CardType.MINION, health=9, metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    r.register_card(CardDefinition(P+'power', 'Spell damage only', CardType.MINION, health=9, spell_damage=5, metadata=META))
    r.register_card(CardDefinition(P+'dormant', 'Dormant enemy slot', CardType.MINION, health=9, dormant_turns=2, metadata=META))
    if mode:
        event = {'install': 'cost_modifier_added', 'pay': 'mana_spent', 'end': 'turn_ended'}[mode]
        def eligible(c):
            if mode == 'end':
                return c.event.player_id == 2 and any(e.spec_id == SPEC and e.remaining_turns == 1
                    for e in c.state.players[1].player_effects)
            cid = RESISTANCE if mode == 'install' else FIREBALL
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == cid
        def watch(c):
            old = next(e for e in c.state.players[1].player_effects if e.spec_id == SPEC)
            who = 2 if mode == 'pay' else 1
            return (RequestChoice(who, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('remove', 'Retire original Aura', (RemovePlayerEffect(1, old.id),)),
                ChoiceOption('replace', 'Retire and install a new original instance', (
                    RemovePlayerEffect(1, old.id), AddPlayerEffect(1, SPEC, old.source_id))),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', 'One real existing notification', CardType.MINION, health=9, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible', uses=1),)))
    r.validate()
    return r


class NativePaladinAuraTests(unittest.TestCase):
    def game(self, hand=(RESISTANCE,), board=(), enemy=(), enemy_hand=(FIREBALL,), mode=None, rules=None):
        self.mode = mode
        if mode:
            board = (*board, P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_04', hand=hand, board=board, deck=(YETI,)*12,
            mana=30, max_mana=30, mana_cap=40), PlayerSetup('HERO_08', hand=enemy_hand, board=enemy,
            deck=(YETI,)*12, mana=30, max_mana=30, mana_cap=40)), seed=132), registry(mode), rules)

    def entity(self, g, cid, pid=1):
        return next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid=RESISTANCE, pid=1, target=None):
        eid = self.entity(g, cid, pid)
        g.apply(PlayCard(pid, eid, target))
        return eid

    def price(self, g, cid=FIREBALL, pid=2):
        # Trusted host operand. The player API must still reject another seat's hand.
        eid = self.entity(g, cid, pid)
        return quote_cost(g._state, g.registry, g._state.entities[eid]).amount

    def effects(self, g, pid=1):
        return [e for e in g.state.players[pid].player_effects if e.spec_id == SPEC]

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry.__wrapped__(self.mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(self.mode)).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('cost_modifier_id', 'cost_modifiers', 'source_allocation', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def rehash_reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(saved, registry.__wrapped__(self.mode))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_full_two_rows_four_faces_native_aura_tags_and_two_enemy_turn_value(self):
        data = load_batch()
        self.assertEqual(len(data['cards']), 2)
        self.assertEqual(len(data['official_observations']), 4)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        r = registry()
        self.assertEqual((r.card(RESISTANCE).cost, r.card(RESISTANCE).spell_school.value), (2, 'holy'))
        self.assertEqual((r.player_effect(SPEC).kind, r.player_effect(SPEC).duration, r.player_effect(SPEC).tick_player), ('aura', 2, 'opponent'))
        self.assertEqual((r.card(TIMEWAYS).cost, r.card(TIMEWAYS).attack, r.card(TIMEWAYS).health, r.card(TIMEWAYS).metadata.tribes), (4, 3, 3, ('elemental',)))

    def test_old_complete_cards_pool_and_default_content_remain_unchanged(self):
        with patch('hs_sim.cards.native_paladin_aura_cards.register_native_paladin_aura_cards', lambda r: None):
            old = build_registry()
        new = build_registry()
        self.assertEqual(set(new.cards)-set(old.cards), {RESISTANCE, TIMEWAYS})
        self.assertTrue(all(asdict(c) == asdict(new.card(cid)) for cid,c in old.cards.items()))
        self.assertEqual(dict(new.pool_cards), dict(old.pool_cards))
        self.assertEqual(dict(new.pools), dict(old.pools))
        self.assertEqual(dict(new.generation_families), dict(old.generation_families))
        from hs_sim.engine.representative import build_registry as defaults
        from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
        self.assertEqual(defaults().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_native_install_changes_only_opponent_spells_and_keeps_player_query_boundary(self):
        g = self.game(hand=(RESISTANCE, FIREBALL), enemy_hand=(FIREBALL, YETI))
        enemy = self.entity(g, FIREBALL, 2)
        with self.assertRaises(IllegalAction):
            g.quote_cost(enemy)
        self.play(g)
        self.assertEqual((self.price(g), self.price(g, pid=1), self.price(g, YETI)), (5, 4, 4))
        effect, = self.effects(g)
        modifier, = g.state.players[2].cost_modifiers
        self.assertEqual((effect.cost_modifier_id, modifier.source_id), (modifier.id, effect.source_id))
        self.assertIsNone(modifier.uses_remaining)
        self.portable(g)

    def test_two_actual_enemy_ends_expire_after_own_ends_do_not_tick(self):
        g = self.game()
        self.play(g)
        for pid, remaining, cost in ((1,2,5),(2,1,5),(1,1,5),(2,None,4)):
            g.apply(EndTurn(pid))
            self.assertEqual([e.remaining_turns for e in self.effects(g)], [] if remaining is None else [remaining])
            self.assertEqual(self.price(g), cost)
        self.assertFalse(g.state.players[2].cost_modifiers)
        self.portable(g)

    def test_two_instances_stack_and_explicit_removal_retires_only_its_modifier(self):
        g = self.game(hand=(RESISTANCE, RESISTANCE, P+'remove'))
        self.play(g)
        self.play(g)
        self.assertEqual(self.price(g), 6)
        old_ids = [e.cost_modifier_id for e in self.effects(g)]
        self.play(g, P+'remove')
        self.assertEqual(self.price(g), 5)
        self.assertEqual([m.id for m in g.state.players[2].cost_modifiers], old_ids[1:])
        self.cycle(g)
        self.cycle(g)
        self.assertEqual(self.price(g), 4)
        self.portable(g)

    def test_repeated_one_physical_spell_allocates_independent_logical_cost_sources(self):
        g = self.game(board=(P+'repeat',))
        source = self.play(g)
        instances = self.effects(g)
        self.assertEqual(len(instances), 2)
        self.assertEqual({e.source_id for e in instances}, {source})
        self.assertEqual(len({e.cost_modifier_id for e in instances}), 2)
        self.assertEqual((g.state.players[1].mana, self.price(g)), (28, 6))
        self.portable(g)

    def test_ordinary_acquisition_order_with_cost_setters_and_unrelated_modifiers_is_preserved(self):
        for hand in ((P+'tax_set',RESISTANCE),(RESISTANCE,P+'tax_set')):
            with self.subTest(hand=hand):
                g = self.game(hand=hand)
                for cid in hand:
                    self.play(g, cid)
                self.assertEqual(self.price(g), 1 if hand[0] == P+'tax_set' else 0)
                self.cycle(g)
                self.cycle(g)
                self.assertEqual(self.price(g), 0)
                self.assertEqual(len(g.state.players[2].cost_modifiers), 1)

    def test_both_owners_have_independent_clocks_and_pay_the_other_owner_tax(self):
        g = self.game(hand=(RESISTANCE,FIREBALL), enemy_hand=(RESISTANCE,FIREBALL))
        self.play(g)
        g.apply(EndTurn(1))
        before = g.state.players[2].mana
        self.play(g, pid=2)
        self.assertEqual(before-g.state.players[2].mana, 3)
        self.assertEqual((self.price(g), self.price(g,pid=1)), (5,5))
        g.apply(EndTurn(2))
        self.assertEqual(([e.remaining_turns for e in self.effects(g,1)], [e.remaining_turns for e in self.effects(g,2)]), ([1],[2]))
        self.portable(g)

    def test_timeways_real_battlecry_uses_one_minion_ability_batch_without_spell_power(self):
        g = self.game(hand=(RESISTANCE,TIMEWAYS), board=(P+'power',), enemy=(YETI,SQUIRE,P+'dormant'))
        self.play(g)
        self.play(g, TIMEWAYS)
        p = g.state.players[2]
        self.assertEqual(g.state.entities[p.hero_id].health, 27)
        self.assertEqual(g.state.entities[p.board[0]].health, 2)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[p.board[1]].keywords)
        self.assertEqual(g.state.entities[p.board[2]].health, 9)
        self.portable(g)

    def test_timeways_without_native_aura_with_legacy_objective_or_only_opponent_aura_does_nothing(self):
        g = self.game(hand=(TIMEWAYS,), enemy=(YETI,))
        self.play(g, TIMEWAYS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        legacy = registry().card(P+'legacy_objective').ongoing_effect_id
        self.assertNotEqual(registry().player_effect(legacy).kind, 'aura')
        g = self.game(hand=(P+'legacy_objective',TIMEWAYS), enemy=(YETI,))
        self.play(g, P+'legacy_objective')
        self.play(g, TIMEWAYS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        g = self.game(hand=(TIMEWAYS,), enemy_hand=(RESISTANCE,))
        g.apply(EndTurn(1));self.play(g,pid=2);g.apply(EndTurn(2));self.play(g,TIMEWAYS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_ordinary_summon_does_not_execute_battlecry_and_native_repeat_runs_twice(self):
        g = self.game(hand=(RESISTANCE,P+'summon'), enemy=(YETI,))
        self.play(g);self.play(g,P+'summon')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        g = self.game(hand=(RESISTANCE,TIMEWAYS), board=(P+'bc_repeat',))
        self.play(g);self.play(g,TIMEWAYS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)

    def test_install_notification_wait_has_complete_binding_restore_and_late_rollback(self):
        g = self.game(mode='install')
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.price(g), 5)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g,'bad')
        self.assertEqual(g.snapshot(), saved)
        for h in (g,other):
            self.choose(h,'remove')
            self.assertFalse(self.effects(h));self.assertEqual(self.price(h),4)
            self.assertEqual(h.state.players[1].mana,28)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_paid_spell_keeps_original_price_when_aura_is_removed_during_payment_wait(self):
        g = self.game(mode='pay')
        self.play(g);g.apply(EndTurn(1))
        before = g.state.players[2].mana
        self.play(g,FIREBALL,2,g.state.players[1].hero_id)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(before-g.state.players[2].mana,5)
        other = self.portable(g)
        for h in (g,other):
            self.choose(h,'remove')
            self.assertEqual(before-h.state.players[2].mana,5)
            self.assertEqual(h.state.entities[h.state.players[1].hero_id].health,24)
            self.assertFalse(self.effects(h))
        self.assertEqual(g.snapshot(),other.snapshot())
        self.portable(g)

    def test_instance_created_by_captured_enemy_end_does_not_consume_that_old_tick(self):
        g = self.game(mode='end')
        self.play(g);self.cycle(g)
        original = self.effects(g)[0]
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        for h in (g,other):
            self.choose(h,'replace')
            new, = self.effects(h)
            self.assertNotEqual((new.id,new.cost_modifier_id),(original.id,original.cost_modifier_id))
            self.assertEqual((new.remaining_turns,self.price(h)),(2,5))
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_ongoing_area_capacity_rejects_before_payment_and_creates_no_orphan_modifier(self):
        g = self.game(hand=(RESISTANCE,RESISTANCE), rules=Ruleset(max_ongoing_effects=1))
        self.play(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g)
        self.assertEqual(g.snapshot(),saved)
        self.assertEqual(len(g.state.players[2].cost_modifiers),1)

    def test_missing_swapped_or_rewritten_binding_is_rejected_after_rehash(self):
        g = self.game(board=(P+'repeat',));self.play(g)
        original=g.snapshot()
        # These are typed live source relationships, not a claim of save authentication.
        for mode in ('missing','duplicate','amount'):
            saved=deepcopy(original)
            owner=saved['state']['players']['1'];other=saved['state']['players']['2']
            if mode=='missing':owner['player_effects'][0]['cost_modifier_id']=None
            elif mode=='duplicate':owner['player_effects'][1]['cost_modifier_id']=owner['player_effects'][0]['cost_modifier_id']
            else:other['cost_modifiers'][0]['spec']['delta']=2
            self.rehash_reject(saved)

    def test_non_aura_clock_tax_and_invalid_native_carriers_are_rejected(self):
        for kwargs in (dict(kind='objective',duration=2,tick_event='turn_ended',tick_player='opponent'),
                       dict(kind='persistent',opponent_spell_cost=1),
                       dict(kind='aura',duration=2,tick_event='turn_ended',opponent_spell_cost=True)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                PlayerEffectSpec(P+'invalid',RESISTANCE,**kwargs)
        r=build_registry();r.register_card(CardDefinition(P+'wrong','Wrong native Aura',CardType.MINION,health=1,metadata=META))
        r.register_player_effect(PlayerEffectSpec(P+'invalid',P+'wrong',kind='aura',duration=2,tick_event='turn_ended'))
        with self.assertRaisesRegex(ValueError,'own typed ongoing spell'):
            r.validate()

    def test_removing_live_aura_from_save_cannot_leave_a_permanent_orphan_tax(self):
        g=self.game();self.play(g);original=g.snapshot()
        saved=deepcopy(original);saved['state']['players']['1']['player_effects']=[]
        self.rehash_reject(saved)
        saved=deepcopy(original);saved['state']['players']['2']['cost_modifiers'][0]['player_effect_id']=999999
        self.rehash_reject(saved)

    def test_previous_schema_is_rejected(self):
        g=self.game();self.play(g);saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved,registry())

    def test_automatic_cast_uses_its_actual_aura_spell_source_without_paying_two_mana(self):
        from hs_sim.engine.spell_casts import CastSpell
        def fresh():
            r=registry.__wrapped__()
            r.register_behavior(P+'automatic_aura',lambda c:(CastSpell(c.player_id,RESISTANCE,c.source_id),))
            r.register_card(CardDefinition(P+'automatic_aura','Actual automatic Aura',CardType.SPELL,
                on_play=P+'automatic_aura',metadata=META))
            r.validate();return r
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=(P+'automatic_aura',)),
            PlayerSetup('HERO_08',hand=(FIREBALL,)))),fresh())
        self.play(g,P+'automatic_aura')
        instance,=self.effects(g)
        self.assertEqual(g.state.entities[instance.source_id].card_id,RESISTANCE)
        self.assertEqual([c.card_id for c in g.state.cast_history],[P+'automatic_aura',RESISTANCE])
        self.assertEqual((g.state.players[1].mana,self.price(g)),(0,5))
        saved=g.snapshot()
        self.assertEqual(Game.from_snapshot(saved,fresh()).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fresh()).snapshot(),saved)


if __name__ == '__main__':
    unittest.main()
