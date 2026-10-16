"""Real ten-gift inventory, individual bodies and their shared lifetime boundary."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CostSpec, CreatedMinionGrant, DARK_GIFTS, DiscoverFromPool, DiscoveryGiftPool,
    EndTurn, Game, GenerationContext, GrantDarkGift, Keyword,
    PlayCard, PlayerSetup, PoolCard, PoolDefinition, PoolMember, PoolQuery,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, SummonStats, TriggerSpec, dark_gift_pool)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage, Destroy,
    Draw, GainArmor, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.model import BattlecryRepeatSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference
from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.dark_gift_cards import INVENTORY_HASH, MINION_POOL_ID
from hs_sim.engine.representative import build_registry
from hs_sim.targets import canonical_digest, load_baseline


GIFTS = {g.id: g for g in DARK_GIFTS}
CONTEXT = GenerationContext('dark-gifts-complete-test', 'experimental')
MINIONS = ('dg.body.a', 'dg.body.b', 'dg.body.c')


def registry(gift_ids=None, *, dormant=False, targeted=False, source_cost=None,
             choice_body=False, copy_wait=False, fail_created=False, unknown_pool=False):
    r = Registry('dark-gifts-complete-test-v1')
    r.register_card(CardDefinition('dg.hero', 'Hero', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.MAGE,), None)))
    def battlecry(c):
        if choice_body:
            return (RequestChoice(c.player_id, (
                ChoiceOption('armor', 'Gain armor', (GainArmor(c.player_id, 1),)),), c.source_id),)
        return (Damage(c.target_id, 1),) if targeted else (GainArmor(c.player_id, 1),)
    r.register_behavior('dg.battlecry', battlecry)
    for cid in MINIONS:
        card = CardDefinition(cid, cid, CardType.MINION, cost=3, attack=4, health=4,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), None),
            battlecry=None if dormant else 'dg.battlecry', requires_target=targeted,
            dormant_turns=2 if dormant else 0)
        r.register_card(card)
        r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition('dg.filler', 'Filler', CardType.MINION, attack=1, health=1))
    r.register_card(CardDefinition('dg.brann', 'Repeat source', CardType.MINION, health=4,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    members = tuple(PoolMember(cid) for cid in MINIONS)
    if unknown_pool:
        r.register_pool_card(PoolCard('dg.unknown', CardType.MINION, 3,
            CardMetadata(True, (CardClass.NEUTRAL,), None)))
        members += (PoolMember('dg.unknown'),)
    r.register_pool(PoolDefinition('dg.minions', 'v1', CONTEXT.target_id, CONTEXT.mode, members))
    members = DARK_GIFTS if gift_ids is None else tuple(GIFTS[cid] for cid in gift_ids)
    pool = DiscoveryGiftPool('dg.gifts', 'v1', CONTEXT.target_id, CONTEXT.mode,
                             members, complete=gift_ids is None)
    r.register_behavior('dg.discover', lambda c: (
        DiscoverFromPool(c.player_id, 'dg.minions',
            PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current'),
            source_id=c.source_id, gift_pool=pool, cost=source_cost),))
    r.register_card(CardDefinition('dg.discover', 'Discover', CardType.SPELL,
        cost=1, on_play='dg.discover'))
    bodies = {
        'kill': lambda c: (Destroy(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'basecopy': lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        'draw': lambda c: (Draw(c.player_id),),
        'buff': lambda c: (Buff(c.target_id, 2, 1),),
    }
    for key, body in bodies.items():
        r.register_behavior('dg.'+key, body)
        r.register_card(CardDefinition('dg.'+key, key, CardType.SPELL,
            on_play='dg.'+key, requires_target=key != 'draw'))
    def grant(c):
        eid = c.state.players[c.player_id].deck[0]
        return (GrantDarkGift(CardReference.capture(c.state.entities[eid]),
                              'EDR_100t7', c.source_id),)
    r.register_behavior('dg.grant', grant)
    r.register_card(CardDefinition('dg.grant', 'Grant', CardType.SPELL, on_play='dg.grant'))
    if copy_wait:
        def wait(c):
            target = c.state.entities[c.event.target_id]
            if target.origin_entity_id is None:
                return ()
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', ()),), c.source_id),)
        r.register_behavior('dg.wait', wait)
        r.register_card(CardDefinition('dg.wait', 'Wait observer', CardType.MINION, health=4,
            triggers=(TriggerSpec('minion_summoned', 'dg.wait'),)))
    if fail_created:
        def fail(c):
            if c.state.entities[c.event.target_id].card_id in MINIONS:
                raise ResolutionError('Diagnostic gift creation failure')
            return ()
        r.register_behavior('dg.fail', fail)
        r.register_card(CardDefinition('dg.fail', 'Fail observer', CardType.MINION, health=4,
            triggers=(TriggerSpec('card_created', 'dg.fail'),)))
    return r


class DarkGiftsCompleteTests(unittest.TestCase):
    def game(self, gift_ids=None, *, dormant=False, targeted=False, source_cost=None,
             choice_body=False, copy_wait=False, fail_created=False, unknown_pool=False,
             hand=('dg.discover',), board=(), deck=('dg.body.a',), seed=22):
        self.options = dict(gift_ids=gift_ids, dormant=dormant, targeted=targeted,
                            source_cost=source_cost, choice_body=choice_body, copy_wait=copy_wait,
                            fail_created=fail_created, unknown_pool=unknown_pool)
        r = registry(**self.options)
        return Game.from_scenario(Scenario((
            PlayerSetup('dg.hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('dg.hero', deck=('dg.filler',)*8, mana=10, max_mana=10)),
            seed=seed, generation_context=CONTEXT), r)

    def play(self, g, cid, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target))
        return eid

    def choose(self, g, gift_id):
        option = next(o for o in g._frame.options if o.effects[0].selection.gift.id == gift_id)
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        eid = next(e.target_id for e in reversed(g.events) if e.kind == 'card_created')
        return eid, option

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved, registry(**self.options)),
                      g.clone(), replay(build_replay(g), registry(**self.options))):
            self.assertEqual(other.snapshot(), saved)
        return saved

    def forced(self, wanted):
        return (wanted, *tuple(cid for cid in ('EDR_100t', 'EDR_100t1', 'EDR_100t8') if cid != wanted)[:2])

    def obtain(self, gift_id, **kwargs):
        g = self.game(self.forced(gift_id), **kwargs)
        self.play(g, 'dg.discover')
        eid, option = self.choose(g, gift_id)
        return g, eid, option

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def test_ten_official_recipes_keep_unconfirmed_raw_faces_out_of_results(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root/'data/support/dark-gifts-core.json').read_text(encoding='utf-8'))
        self.assertEqual(canonical_digest(data), INVENTORY_HASH)
        self.assertEqual(set(data['formal_gift_ids']), set(GIFTS))
        self.assertEqual(len(GIFTS), 10)
        self.assertEqual(set(data['retained_unconfirmed_faces']), {'EDR_100t4', 'EDR_100t10'})
        raw_ids = {r['id'] for r in data['records']}
        self.assertTrue({'EDR_100t4', 'EDR_100t10'}.issubset(raw_ids))
        pool = dark_gift_pool(CONTEXT.target_id)
        self.assertTrue(pool.complete)
        self.assertEqual(pool.members, DARK_GIFTS)
        self.assertFalse(data['formal_minion_pool_verified'])
        self.assertFalse(data['CN_timing_calibrated'])

    def test_keyword_gifts_reject_any_redundant_keyword(self):
        plain = CardDefinition('plain', 'Plain', CardType.MINION, attack=4, health=4)
        for gift in DARK_GIFTS:
            for keyword in gift.grant.keywords:
                with self.subTest(gift=gift.id, keyword=keyword):
                    self.assertFalse(gift.eligible(replace(plain, keywords=(keyword,))))
        self.assertTrue(GIFTS['EDR_100t13'].eligible(plain))

    def test_attack_and_printed_battlecry_qualification(self):
        plain = CardDefinition('plain', 'Plain', CardType.MINION, attack=3, health=4)
        self.assertTrue(GIFTS['EDR_100t2'].eligible(plain))
        self.assertFalse(GIFTS['EDR_100t2'].eligible(replace(plain, attack=2)))
        self.assertFalse(GIFTS['EDR_100t6'].eligible(replace(plain, attack=0)))
        self.assertTrue(GIFTS['EDR_100t6'].eligible(replace(plain, attack=1)))
        self.assertFalse(GIFTS['EDR_100t7'].eligible(plain))
        self.assertTrue(GIFTS['EDR_100t7'].eligible(replace(plain, battlecry='bc')))
        self.assertFalse(GIFTS['EDR_100t5'].eligible(CardDefinition('spell', 'Spell', CardType.SPELL)))

    def test_unknown_special_grants_and_unknown_real_gift_ids_fail_explicitly(self):
        for special in ('invented', True, 1, (), []):
            with self.subTest(special=special), self.assertRaises(ValueError):
                CreatedMinionGrant(special=special)
        g = self.game()
        ref = CardReference.capture(g.state.entities[g.state.players[1].deck[0]])
        for cid in ('EDR_100t4', 'EDR_100t10', 'unknown'):
            with self.subTest(cid=cid), self.assertRaises(ValueError):
                GrantDarkGift(ref, cid)

    def test_full_pool_offers_three_different_eligible_bindings(self):
        for seed in (1, 22, 53):
            g = self.game(seed=seed)
            self.play(g, 'dg.discover')
            options = g._frame.options
            selected = [o.effects[0].selection for o in options]
            self.assertEqual(len({p.gift.id for p in selected}), 3)
            self.assertEqual(len({p.card_id for p in selected}), 3)
            self.assertTrue(all(p.gift.eligible(g.registry.card(p.card_id)) for p in selected))

    def test_actual_choice_waiting_resumes_same_gift_without_random_or_payment(self):
        g = self.game(self.forced('EDR_100t5'))
        self.play(g, 'dg.discover')
        saved = self.portable(g)
        eid, option = self.choose(g, 'EDR_100t5')
        other = Game.from_snapshot(saved, registry(**self.options))
        self.choose(other, 'EDR_100t5')
        self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual(g.snapshot()['rng_state'], saved['rng_state'])
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(public_gifts(g.state.entities[eid]), [{'id': 'EDR_100t5', 'name': '活体梦魇'}])

    def test_source_reduction_and_gift_reduction_preview_match_delivered_cost(self):
        g, eid, option = self.obtain('EDR_100t2', source_cost=CostSpec(delta=-2))
        entity = g.state.entities[eid]
        self.assertEqual((option.preview.cost, entity.cost, entity.attack), (0, 0, 2))
        self.play(g, option.card_id)
        self.assertEqual(g.state.players[1].mana, 9)
        self.portable(g)

    def test_special_gifts_retain_source_reduction(self):
        for gift_id in ('EDR_100t5', 'EDR_100t7'):
            g, eid, option = self.obtain(gift_id, source_cost=CostSpec(delta=-2))
            self.assertEqual((option.preview.cost, g.state.entities[eid].cost), (1, 1))
            self.play(g, option.card_id)
            self.assertEqual(g.state.players[1].mana, 8)
            self.portable(g)

    def test_rude_awakening_repeats_only_own_battlecry_with_one_paid_play(self):
        g, eid, option = self.obtain('EDR_100t7')
        self.play(g, option.card_id)
        self.assertEqual(self.hero(g).armor, 2)
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.assertEqual(len(g.state.play_history), 2)
        self.assertEqual(g.state.players[1].mana, 6)
        self.portable(g)

    def test_rude_awakening_keeps_original_target_for_both_battlecries(self):
        g, eid, option = self.obtain('EDR_100t7', targeted=True)
        self.play(g, option.card_id, self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.portable(g)

    def test_rude_awakening_and_existing_repeat_source_use_shared_max_policy(self):
        g, eid, option = self.obtain('EDR_100t7', board=('dg.brann',))
        self.play(g, option.card_id)
        self.assertEqual(self.hero(g).armor, 2)
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.portable(g)

    def test_living_nightmare_summons_current_two_two_without_copy_battlecry(self):
        g, eid, option = self.obtain('EDR_100t5')
        self.play(g, option.card_id)
        copies = [g.state.entities[i] for i in g.state.players[1].board if i != eid]
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual((copy.attack, copy.health, copy.origin_entity_id), (2, 2, eid))
        self.assertEqual(public_gifts(copy), public_gifts(g.state.entities[eid]))
        self.assertEqual(self.hero(g).armor, 1)
        self.assertEqual(len(g.state.play_history), 2)
        self.assertEqual(g.state.players[1].mana, 6)
        self.portable(g)

    def test_living_nightmare_copies_dormant_body_and_both_awaken(self):
        g, eid, option = self.obtain('EDR_100t5', dormant=True)
        self.play(g, option.card_id)
        board = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual(len(board), 2)
        self.assertTrue(all(e.dormancy is not None for e in board))
        self.assertEqual((board[1].attack, board[1].max_health), (2, 2))
        self.portable(g)
        for _ in range(4):
            g.apply(EndTurn(g.state.active_player))
        self.assertTrue(all(g.state.entities[e.id].active for e in board))
        self.assertEqual((g.state.entities[board[1].id].attack, g.state.entities[board[1].id].health), (2, 2))
        self.portable(g)

    def test_living_nightmare_full_board_preserves_original_play(self):
        g, eid, option = self.obtain('EDR_100t5', board=('dg.filler',)*6)
        self.play(g, option.card_id)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertIn(eid, g.state.players[1].board)
        self.assertEqual(self.hero(g).armor, 1)
        self.portable(g)

    def test_current_copy_keeps_gift_and_base_copy_drops_it(self):
        g, eid, option = self.obtain('EDR_100t7', hand=('dg.discover', 'dg.copy', 'dg.basecopy'))
        self.play(g, option.card_id)
        self.play(g, 'dg.copy', eid)
        current = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual(public_gifts(current), public_gifts(g.state.entities[eid]))
        self.assertTrue({a.id for a in current.abilities}.isdisjoint({a.id for a in g.state.entities[eid].abilities}))
        self.play(g, 'dg.basecopy', eid)
        self.assertEqual(public_gifts(g.state.entities[g.state.players[1].board[-1]]), [])
        self.portable(g)

    def test_silence_removes_gift_but_keeps_shared_printed_identity(self):
        g, eid, option = self.obtain('EDR_100t7', hand=('dg.discover', 'dg.silence'))
        self.play(g, option.card_id)
        self.play(g, 'dg.silence', eid)
        self.assertEqual(public_gifts(g.state.entities[eid]), [])
        self.assertFalse(any(a.kind == 'battlecry_repeat' for a in g.state.entities[eid].abilities))
        self.portable(g)

    def test_bounce_clears_gift_before_second_ordinary_battlecry(self):
        g, eid, option = self.obtain('EDR_100t7', hand=('dg.discover', 'dg.bounce'))
        self.play(g, option.card_id)
        self.play(g, 'dg.bounce', eid)
        self.assertEqual(public_gifts(g.state.entities[eid]), [])
        self.play(g, option.card_id)
        self.assertEqual(self.hero(g).armor, 3)
        self.portable(g)

    def test_full_health_reborn_keeps_local_gift_and_buff(self):
        g, eid, option = self.obtain('EDR_100t9', hand=('dg.discover', 'dg.buff', 'dg.kill'))
        self.play(g, option.card_id)
        self.play(g, 'dg.buff', eid)
        self.play(g, 'dg.kill', eid)
        returned = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((returned.attack, returned.health), (6, 5))
        self.assertNotIn(Keyword.REBORN, returned.keywords)
        self.assertEqual(public_gifts(returned), [{'id': 'EDR_100t9', 'name': '回荡恐怖'}])
        self.portable(g)

    def test_sweet_dreams_creates_at_deck_top_and_draw_keeps_actual_material(self):
        g, eid, option = self.obtain('EDR_100t8', hand=('dg.discover', 'dg.draw'), source_cost=CostSpec(delta=-2))
        entity = g.state.entities[eid]
        self.assertEqual(g.state.players[1].deck[0], eid)
        self.assertEqual((entity.zone, entity.attack, entity.max_health, entity.cost), (Zone.DECK, 8, 9, 1))
        self.assertFalse(any(e.kind == 'card_added_to_hand' and e.target_id == eid for e in g.events))
        self.play(g, 'dg.draw')
        self.assertIn(eid, g.state.players[1].hand)
        self.assertEqual((entity.attack, entity.max_health, entity.cost), (8, 9, 1))
        self.portable(g)

    def test_own_gift_names_are_visible_and_enemy_hand_receipts_stay_private(self):
        g, eid, option = self.obtain('EDR_100t5')
        own = g.for_player(1).observe()
        enemy = g.for_player(2).observe()
        own_wire = json.dumps(own, ensure_ascii=False)
        enemy_wire = json.dumps(enemy, ensure_ascii=False)
        self.assertIn('活体梦魇', own_wire)
        self.assertNotIn('活体梦魇', enemy_wire)
        self.assertNotIn(option.card_id, enemy_wire)
        for field in ('next_attachment_id', 'offered_gifts', 'pool_discovery_picked', 'resolution_frame'):
            self.assertNotIn(field, own_wire)
            self.assertNotIn(field, enemy_wire)

    def test_existing_deck_minion_can_receive_gift_without_allocation_or_draw(self):
        g = self.game(hand=('dg.grant', 'dg.draw'))
        eid = g.state.players[1].deck[0]
        next_id = g.state.next_entity_id
        self.play(g, 'dg.grant')
        self.assertEqual(g.state.next_entity_id, next_id)
        self.assertEqual(g.state.players[1].deck[0], eid)
        self.assertEqual(public_gifts(g.state.entities[eid]), [{'id': 'EDR_100t7', 'name': '粗暴唤醒'}])
        self.assertNotIn('粗暴唤醒', json.dumps(g.for_player(2).observe(), ensure_ascii=False))
        self.play(g, 'dg.draw')
        self.play(g, 'dg.body.a')
        self.assertEqual(self.hero(g).armor, 2)
        self.portable(g)

    def test_previous_snapshot_schema_is_rejected(self):
        g = self.game()
        saved = g.snapshot()
        self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version'] = 265
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry())

    def test_rude_awakening_resumes_each_real_battlecry_choice_with_one_payment(self):
        g, eid, option = self.obtain('EDR_100t7', choice_body=True)
        self.play(g, option.card_id)
        for iteration in (1, 2):
            self.assertIsNotNone(g.state.pending_choice)
            self.assertEqual(g.state.players[1].mana, 6)
            self.portable(g)
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, (q.options[0].id,)))
            self.assertEqual(self.hero(g).armor, iteration)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_copied_dormant_body_waiting_restores_accepted_material_and_clock(self):
        g, eid, option = self.obtain('EDR_100t5', dormant=True, copy_wait=True, board=('dg.wait',))
        self.play(g, option.card_id)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (q.options[0].id,)))
        copied = [g.state.entities[i] for i in g.state.players[1].board
                  if g.state.entities[i].origin_entity_id == eid][0]
        self.assertIsNotNone(copied.dormancy)
        self.assertEqual((copied.attack, copied.max_health), (2, 2))
        self.portable(g)

    def test_exception_after_actual_gift_selection_rolls_back_entire_delivery(self):
        g = self.game(self.forced('EDR_100t7'), fail_created=True, board=('dg.fail',))
        self.play(g, 'dg.discover')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Diagnostic gift creation failure'):
            self.choose(g, 'EDR_100t7')
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_unknown_matching_minion_is_not_silently_filtered(self):
        g = self.game(unknown_pool=True)
        before = g.snapshot()
        with self.assertRaisesRegex(Exception, r'dg\.unknown'):
            self.play(g, 'dg.discover')
        self.assertEqual(g.snapshot(), before)

    def test_two_real_sources_use_the_full_gift_inventory_with_explicit_minion_scope(self):
        target = load_baseline().target['target_id']
        r = build_registry()
        self.assertEqual((r.version, len(r.cards)), ('representative-m5-v65', 311))
        for cid in ('EDR_105', 'FIR_900'):
            g = Game.from_scenario(Scenario((
                PlayerSetup('HERO_08', hand=(cid,), mana=10, max_mana=10),
                PlayerSetup('HERO_08', deck=('CS2_118',)*8, mana=10, max_mana=10)),
                seed=12, generation_context=GenerationContext(target, 'experimental')), build_registry())
            eid = g.state.players[1].hand[0]
            g.apply(PlayCard(1, eid))
            saved = g.snapshot()
            self.assertEqual(Game.from_snapshot(saved, build_registry()).snapshot(), saved)
            spec = g._frame.options[0].effects[0].batch.spec
            self.assertEqual(spec.pool_id, MINION_POOL_ID)
            self.assertEqual(len(spec.gift_pool.members), 10)
            self.assertTrue(spec.gift_pool.complete)
            option = g._frame.options[0]
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
            self.assertEqual(replay(build_replay(g), build_registry()).snapshot(), g.snapshot())


if __name__ == '__main__':
    unittest.main()
