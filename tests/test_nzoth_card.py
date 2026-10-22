"""Real N'Zoth skills, entry-time Deathrattle pricing and original continuations."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.nzoth_card import CARD, CALL, ARMY, DOMAIN, CONTROL, SKILLS, load_batch, register_nzoth_card
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseMinionAbility)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, GainArmor,
    GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, DamageKind, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import canonical, check_face

P = 'fixture.nzoth.'
A, B, C, CHEAP, PLAIN, FOREIGN, SHIELD, REBORN, DORMANT, MANY, CLEAN, SUMMON_ONE, KILL, QUIET, MORPH, BOUNCE, COPY, GIVE, TAKE, WATCH, UNKNOWN = (
    P+x for x in ('five', 'six', 'eight', 'cheap', 'plain', 'foreign', 'shield', 'reborn', 'dormant',
                  'many', 'clean', 'summon', 'kill', 'silence', 'morph', 'bounce', 'copy', 'give', 'take', 'watch', 'unknown'))
TARGET = 'fixture.nzoth'


@lru_cache(maxsize=None)
def fixture(mode=None, pool='normal', role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_nzoth_card(r)
    for n in (1, 2, 3): r.register_behavior(P+'death'+str(n), lambda c, n=n: (GainArmor(c.player_id, n),))
    for cid, cost, body, cls in ((A, 5, 1, CardClass.MAGE), (B, 6, 2, CardClass.NEUTRAL),
            (C, 8, 3, CardClass.NEUTRAL), (CHEAP, 0, 1, CardClass.NEUTRAL),
            (FOREIGN, 5, 1, CardClass.PRIEST), (REBORN, 0, 1, CardClass.NEUTRAL),
            (DORMANT, 0, 1, CardClass.NEUTRAL)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=1, health=4,
            deathrattle=P+'death'+str(body), dormant_turns=1 if cid == DORMANT else 0,
            keywords=(Keyword.REBORN,) if cid == REBORN else (),
            metadata=CardMetadata(True, (cls,), Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid, keywords in ((PLAIN, ()), (SHIELD, (Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=20,
            keywords=keywords, metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    bodies = {MANY: lambda c: tuple(Summon(c.player_id, CHEAP) for _ in range(5)),
        SUMMON_ONE: lambda c: (Summon(c.player_id, CHEAP),),
        CLEAN: lambda c: tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id not in (CARD, WATCH)),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),), QUIET: lambda c: (Silence(c.target_id),),
        MORPH: lambda c: (Transform(c.target_id, PLAIN),), BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        GIVE: lambda c: (GrantDeathrattle(c.target_id, P+'death1', c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid not in (MANY, CLEAN, SUMMON_ONE)))
    def fail(c): raise ResolutionError('Deliberate N Zoth followup failure')
    r.register_behavior(P+'fail', fail)
    if mode:
        def watch(c):
            if c.event is None or c.event.target_id is None: return ()
            target = c.state.entities[c.event.target_id]
            if target.card_id not in (A, B, C, CHEAP): return ()
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(3-c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
            triggers=(TriggerSpec('minion_summoned', WATCH),)))
    members = () if pool == 'empty' else (A, B, C, CHEAP, PLAIN, FOREIGN)
    if pool == 'unknown':
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 5,
            CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON), deathrattle=True))
        members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'v1', TARGET, 'experimental',
        tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class NzothTests(unittest.TestCase):
    def game(self, board=(), hand=(), enemy=(), mode=None, pool='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', board=board, hand=hand, deck=(PLAIN,)*12,
                        mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_01', board=enemy, deck=(PLAIN,)*12, mana=20, max_mana=20, mana_cap=20)),
            seed=179, generation_context=GenerationContext(TARGET, 'experimental')), fixture(mode, pool))

    def play(self, g, cid, target=None):
        entity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(1, entity, target))

    def use(self, g, cid, target=None):
        source = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == CARD)
        return g.apply(UseMinionAbility(1, source, cid, target))

    def choose(self, g, cid):
        q = g.state.pending_choice
        option = next(o for o in q.options if o.card_id == cid or o.id == str(cid))
        return g.apply(SelectChoice(q.player_id, q.id, (option.id,)))

    def cost(self, g, player=1):
        entity = next(g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id == CARD)
        return quote_unselected_cost(g.state, g.registry, entity).amount

    def restore(self, g, mode=None, pool='normal', replay_all=True):
        other = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture(mode, pool, 'reader'))
        self.assertEqual(other.state_hash(), g.state_hash()); self.assertEqual(g.clone().state_hash(), g.state_hash())
        if replay_all: self.assertEqual(replay(build_replay(g), fixture(mode, pool, 'reader')).state_hash(), g.state_hash())
        return other

    def rehash(self, value):
        value['events_hash'] = canonical_hash(value['events'])
        value['state_hash'] = canonical_hash({k: v for k, v in value.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def test_full_records_ten_primary_faces_and_actual_fifteen_cost_five_seven(self):
        data = load_batch(); self.assertEqual(len(data['official_observations']), 10)
        rows = {x['record']['id']: x['record'] for x in data['cards']+data['dependencies']}
        for observation in data['official_observations']:
            raw = rows[observation['card_id']]
            check_face(raw, observation['face'], observation['locale'],
                numeric_normalizations={'cost': 0} if raw['cost'] is None else None)
        self.assertEqual((fixture().card(CARD).cost, fixture().card(CARD).attack, fixture().card(CARD).health), (15, 5, 7))
        self.assertTrue(all(fixture().card(cid).choice_only for cid in SKILLS))

    def test_real_play_pays_fifteen_and_native_skills_never_cast_descriptor_spells(self):
        g = self.game(hand=(CARD,)); self.assertEqual(self.cost(g), 15); self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 5); self.use(g, CALL)
        self.choose(g, A); self.assertEqual(g.state.players[1].mana, 5)
        self.assertEqual(len(g.state.cast_history), 0); self.restore(g)

    def test_discovery_uses_current_class_neutral_printed_five_and_deathrattle(self):
        g = self.game(board=(CARD,)); self.use(g, CALL)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {A, B, C})
        self.choose(g, B)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [CARD, B])
        self.assertEqual(g.state.players[1].mana, 20); self.restore(g)

    def test_unknown_eligible_discovery_fails_without_pruning_or_spending_action(self):
        g = self.game(board=(CARD,), pool='unknown'); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g, CALL)
        self.assertEqual(g.state_hash(), before)

    def test_empty_discovery_preserves_empty_original_domain_without_rng(self):
        g = self.game(board=(CARD,), pool='empty'); rng = g.snapshot()['rng_state']; self.use(g, CALL)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng); self.restore(g, pool='empty')

    def test_initial_board_deaths_and_control_changes_are_not_successful_summons(self):
        g = self.game(board=(CHEAP,), hand=(CARD, TAKE)); self.assertEqual(self.cost(g), 15)
        self.play(g, TAKE, g.state.players[1].board[0]); self.assertEqual(self.cost(g), 15)
        self.assertFalse(g.state.successful_summon_history); self.restore(g)

    def test_real_minion_play_and_spell_summon_each_discount_once(self):
        g = self.game(hand=(CARD, CHEAP, SUMMON_ONE)); self.play(g, CHEAP); self.play(g, SUMMON_ONE)
        self.assertEqual(self.cost(g), 13)
        self.assertTrue(all(row.deathrattle_ids for row in g.state.successful_summon_history)); self.restore(g)

    def test_original_entry_trait_survives_later_silence_transform_and_transfer(self):
        g = self.game(hand=(CARD, CHEAP, QUIET, MORPH, TAKE)); self.play(g, CHEAP)
        source = g.state.players[1].board[0]; row = g.state.successful_summon_history[0]
        self.play(g, QUIET, source); self.play(g, MORPH, source); self.play(g, TAKE, source)
        self.assertEqual(self.cost(g), 14); self.assertEqual(g.state.successful_summon_history[0], row); self.restore(g)

    def test_later_grant_does_not_retroactively_discount_but_current_copy_entry_does(self):
        g = self.game(board=(CARD,), hand=(CARD, PLAIN, COPY)); self.play(g, PLAIN)
        target = g.state.players[1].board[-1]; self.use(g, DOMAIN, target)
        self.assertEqual(self.cost(g), 15); self.assertFalse(g.state.successful_summon_history[0].deathrattle_ids)
        self.play(g, COPY, target); self.assertEqual(self.cost(g), 14)
        self.assertTrue(g.state.successful_summon_history[-1].deathrattle_ids); self.restore(g)

    def test_dormant_entry_keeps_declared_deathrattle_trait(self):
        g = self.game(hand=(CARD, DORMANT)); self.play(g, DORMANT)
        self.assertFalse(g.state.entities[g.state.players[1].board[0]].active)
        self.assertEqual(self.cost(g), 14); self.restore(g)

    def test_successful_reborn_counts_a_second_actual_deathrattle_entry(self):
        g = self.game(hand=(CARD, REBORN, KILL)); self.play(g, REBORN)
        self.play(g, KILL, g.state.players[1].board[0]); self.assertEqual(self.cost(g), 13)
        rows = g.state.successful_summon_history
        self.assertEqual(len(rows), 2); self.assertIsNotNone(rows[-1].reborn_death_id); self.restore(g)

    def test_full_board_failed_summons_do_not_discount(self):
        g = self.game(board=(PLAIN,)*7, hand=(CARD, MANY)); self.play(g, MANY)
        self.assertFalse(g.state.successful_summon_history); self.assertEqual(self.cost(g), 15); self.restore(g)

    def test_fifteen_real_deathrattle_entries_reach_zero_and_actual_payment_is_zero(self):
        g = self.game(hand=(MANY, MANY, MANY, CLEAN, CLEAN, CARD))
        for n in range(3):
            self.play(g, MANY)
            if n != 2: self.play(g, CLEAN)
        self.assertEqual(self.cost(g), 0); before = g.state.players[1].mana; self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, before); self.assertEqual(len(g.state.successful_summon_history), 16)
        self.restore(g, replay_all=False)

    def test_army_resurrects_four_distinct_printed_deathrattle_faces_including_silenced(self):
        g = self.game(board=(CARD, A, A, B, C, CHEAP, PLAIN), hand=(GIVE, QUIET, CLEAN, CARD))
        plain = g.state.players[1].board[-1]; first = g.state.players[1].board[1]
        self.play(g, GIVE, plain); self.play(g, QUIET, first); self.play(g, CLEAN); self.use(g, ARMY)
        revived = [g.state.entities[i].card_id for i in g.state.players[1].board if g.state.entities[i].card_id != CARD]
        self.assertEqual(set(revived), {A, B, C, CHEAP}); self.assertEqual(len(revived), 4)
        self.assertEqual(self.cost(g), 11); self.restore(g)

    def test_army_empty_pool_uses_no_rng_and_keeps_native_action_budget(self):
        g = self.game(board=(CARD,)); before = g.snapshot()['rng_state']; self.use(g, ARMY)
        self.assertEqual(g.snapshot()['rng_state'], before); self.assertEqual(len(g.state.players[1].board), 1)
        self.assertTrue(g.state.entities[g.state.players[1].board[0]].old_god_free_used); self.restore(g)

    def test_domain_grants_real_deathrattle_and_control_triggers_each_body_twice(self):
        g = self.game(board=(CARD, PLAIN), enemy=(PLAIN, SHIELD)); target = g.state.players[1].board[-1]
        self.use(g, DOMAIN, target); self.use(g, CONTROL, target)
        enemies = [g.state.entities[i] for i in g.state.players[2].board]
        self.assertEqual([e.health for e in enemies], [16, 18])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        results = [r.health_result for r in g.state.damage_history]
        self.assertTrue(all(r.source_card_id == PLAIN and r.damage_kind == DamageKind.MINION_ABILITY.value for r in results))
        self.assertFalse(g.state.cast_history); self.restore(g)

    def test_domain_and_control_reject_self_enemy_and_missing_targets(self):
        g = self.game(board=(CARD, PLAIN), enemy=(PLAIN,)); before = g.state_hash()
        for target in (None, g.state.players[1].board[0], g.state.players[2].board[0]):
            with self.subTest(target=target), self.assertRaises(IllegalAction): self.use(g, DOMAIN, target)
            self.assertEqual(g.state_hash(), before)

    def test_silence_removes_the_granted_body(self):
        g = self.game(board=(CARD, PLAIN), hand=(QUIET,), enemy=(PLAIN,)); target = g.state.players[1].board[-1]
        self.use(g, DOMAIN, target); self.play(g, QUIET, target); self.use(g, CONTROL, target)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 20); self.restore(g)

    def test_discovery_initial_and_summon_reaction_waits_restore_without_duplicate_entry(self):
        g = self.game(board=(CARD, WATCH), mode='wait'); self.use(g, CALL); self.restore(g, 'wait')
        self.choose(g, A); self.assertIsNotNone(g.state.pending_choice)
        other = self.restore(g, 'wait')
        for branch in (g, other): self.choose(branch, 'ok')
        self.assertEqual(g.state_hash(), other.state_hash()); self.assertEqual(len(g.state.successful_summon_history), 1)
        self.restore(g, 'wait')

    def test_resurrection_reaction_waits_preserve_remaining_distinct_deaths_and_price_facts(self):
        g = self.game(board=(CARD, WATCH, A, B, C, CHEAP), hand=(CLEAN, CARD), mode='wait')
        self.play(g, CLEAN); self.use(g, ARMY); other = self.restore(g, 'wait')
        for branch in (g, other):
            while branch.state.pending_choice: self.choose(branch, 'ok')
            self.assertEqual(self.cost(branch), 11); self.assertEqual(len(branch.state.successful_summon_history), 4)
        self.assertEqual(g.state_hash(), other.state_hash()); self.restore(g, 'wait')

    def test_failed_discovered_summon_rolls_back_new_selection_trait_and_rng(self):
        g = self.game(board=(CARD, WATCH), mode='fail'); self.use(g, CALL); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.choose(g, A)
        self.assertEqual(g.state_hash(), before); self.assertFalse(g.state.successful_summon_history)

    def test_rehashed_state_cannot_drop_or_forge_an_original_deathrattle_entry_trait(self):
        g = self.game(hand=(CARD, CHEAP)); self.play(g, CHEAP)
        for ids in ([], [True], [g.state.next_attachment_id]):
            value = deepcopy(g.snapshot()); value['state']['successful_summon_history'][0]['deathrattle_ids'] = ids
            self.rehash(value)
            with self.subTest(ids=ids), self.assertRaises(SnapshotError):
                Game.from_snapshot(value, fixture(role='reader'))

    def test_original_entry_traits_and_cost_receipts_are_not_player_information(self):
        g = self.game(hand=(CARD, CHEAP)); self.play(g, CHEAP)
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid), ensure_ascii=False)
            self.assertNotIn('deathrattle_ids', visible); self.assertNotIn('_entry_deathrattles', visible)
        self.restore(g)
