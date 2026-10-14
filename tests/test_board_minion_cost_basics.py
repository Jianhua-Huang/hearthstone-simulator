"""Pure continuously derived board prices and genuine frozen hand payments."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CostSpec,
    Game, IllegalAction, InteractableSpec, ModularSelection, PlayCard, PlayerSetup,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    assemble_modular_card)
from hs_sim.engine.costs import (capture_cost_input, capture_quote_fact, capture_generated_quote_fact,
    quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption,
    CopyMinion, Destroy, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.model import BoardMinionCostRow
from hs_sim.engine.interactables import InstallInteractable
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
import test_modular_deck_basics as modular_fixture
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SEA = 'EX1_586'
FRIEND = 'count.friendly'
PATH = Path(__file__).resolve().parents[1] / 'data/support/board-minion-cost-basics.json'
PIN = '8a50f2bdb060ca5115582ec6a6603ba6e4913bb5ea72c3c4bd982b5add0f40bd'


def evidence():
    value = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN: raise ValueError('Board price evidence changed')
    result = {}
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Board price full raw changed')
        result[row['id']] = row['data']
    return result


def registry():
    r = opening_registry(); raw = evidence()[SEA]
    r.register_card(CardDefinition(SEA, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata(rarity=Rarity.EPIC, tribes=()),
        board_minion_cost=BoardMinionCostSpec('all')))
    r.register_card(CardDefinition(FRIEND, 'Synthetic friendly count', CardType.MINION,
        cost=6, attack=2, health=4, metadata=metadata(), board_minion_cost=BoardMinionCostSpec()))
    r.register_card(CardDefinition('sleep', 'Dormant fixture', CardType.MINION, attack=1, health=3, dormant_turns=2))
    r.register_behavior('inert.use', lambda c: ())
    r.register_card(CardDefinition('inert', 'Inert fixture', CardType.MINION, health=1,
        corpse_value=0, interactable=InteractableSpec('inert.use')))
    def first(c): return c.state.players[c.player_id].board[0]
    scripts = {
        'count.summon': lambda c: (Summon(c.player_id, 'card.1'),),
        'count.install': lambda c: (InstallInteractable(c.player_id, 'inert', c.source_id),),
        'count.kill': lambda c: (Destroy(first(c)),),
        'count.control': lambda c: (ChangeControl(c.state.players[3-c.player_id].board[0], c.player_id),),
        'count.silence': lambda c: (Silence(first(c)),),
        'count.bounce': lambda c: (ReturnToHand(first(c)),),
        'count.base': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'count.local': lambda c: (ModifyCost(next(e for e in c.state.players[c.player_id].hand
            if c.state.entities[e].card_id == SEA), CostSpec(delta=-3)),),
        'count.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(SEA,))),),
        'count.fail': lambda c: (Summon(c.player_id, 'card.1'), AddToHand(c.player_id, 'unknown.count.card')),
    }
    for cid, behavior in scripts.items():
        r.register_behavior(cid, behavior)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def pause(c):
        source = c.state.entities[c.event.source_id]
        if source.card_id != SEA: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Remove observer', (Destroy(c.source_id),)),
            ChoiceOption('fault', 'Delayed failure', (InvokeBehavior('count.fail', c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior('count.pause', pause)
    r.register_card(CardDefinition('count.watch', 'Paid completion observer', CardType.MINION,
        attack=1, health=3, triggers=(TriggerSpec('card_played', 'count.pause'),)))
    return r


def native_registry():
    r = modular_fixture.registry()
    raw = evidence()['TOY_330t98']
    r.register_modular_module(CardDefinition(raw['id'], raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'], board_minion_cost=BoardMinionCostSpec()))
    assemble_modular_card(r, ModularSelection('TOY_330', (raw['id'], modular_fixture.PERFECT), 'TOY_330t5'))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class BoardMinionCostTests(unittest.TestCase):
    def game(self, hand=(SEA, FRIEND), board=(), enemy=(), *, mana=10, enemy_hand=(), stored=()):
        self.factory = registry
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, board=board,
            deck=stored, mana=mana, max_mana=10), PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy)), seed=7), registry())

    def source(self, g, cid, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id == cid)

    def fact(self, g, cid=SEA, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, cid=SEA, player=1): return self.fact(g, cid, player).amount

    def play(self, g, cid):
        eid = self.source(g, cid).id; g.apply(PlayCard(1, eid)); return eid

    def choose(self, g, option='ok'):
        choice = g.state.pending_choice; g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, self.factory())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), self.factory()).snapshot(), saved)
        for actor in (1, 2): self.assertEqual(restored.observe(actor), g.observe(actor))
        return saved

    def test_three_complete_raw_records_and_real_formula_text_are_pinned(self):
        rows = evidence()
        original = {r['id']:r for r in json.loads((PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(rows), {'TOY_330t98', SEA, 'CORE_EX1_586'})
        for cid, raw in rows.items(): self.assertEqual(raw, original[cid])
        self.assertIn('friendly minion', rows['TOY_330t98']['text_en'])
        self.assertIn('minion on the battlefield', rows[SEA]['text_en'])
        self.assertEqual((rows[SEA]['cost'], rows[SEA]['attack'], rows[SEA]['health']), (10, 8, 8))

    def test_only_finite_scopes_and_ordinary_minion_declarations_are_accepted(self):
        for invalid in (True, 'enemy', 'expression', None):
            with self.assertRaises(ValueError): BoardMinionCostSpec(invalid)
        with self.assertRaises(ValueError): BoardMinionCostSpec(profile_id='unknown')
        r = registry()
        for changes in ({'kind': CardType.SPELL, 'health': 0}, {'board_minion_cost': 'formula'},
                {'interactable': InteractableSpec('inert.use')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(SEA), id='bad.' + str(len(r.cards)), **changes))

    def test_empty_board_hand_and_deck_cards_do_not_reduce_cost(self):
        g = self.game(hand=(SEA, FRIEND, 'card.1'), stored=('card.2',))
        f = self.fact(g)
        self.assertEqual((f.amount, f.intrinsic.board_minions.quantity), (10, 0))
        self.assertEqual(f.intrinsic.board_minions.boards, ((), ()))
        self.assertEqual(self.price(g, FRIEND), 6); self.portable(g)

    def test_friendly_and_all_scopes_use_actual_payer_and_both_complete_boards(self):
        g = self.game(board=('card.1',), enemy=('card.2','card.3'), enemy_hand=(FRIEND,))
        self.assertEqual((self.price(g), self.price(g, FRIEND), self.price(g, FRIEND, 2)), (7, 5, 4))
        f = self.fact(g, FRIEND).intrinsic.board_minions
        self.assertEqual(tuple(map(len, f.boards)), (1, 2)); self.assertEqual(f.quantity, 1)
        self.assertEqual(tuple(r.entity_id for r in f.boards[1]), tuple(g.state.players[2].board))

    def test_zero_floor_and_price_queries_do_not_write_state_rng_or_attachments(self):
        g = self.game(board=tuple(f'card.{i}' for i in range(1,8)), enemy=tuple(f'card.{i}' for i in range(8,15)))
        before = g.snapshot(); self.assertEqual((self.price(g), self.price(g, FRIEND)), (0, 0))
        for _ in range(3):
            self.fact(g); quote_cost(g.state, g.registry, self.source(g, SEA)); g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)

    def test_dormant_minions_count_and_inert_board_objects_are_not_minions(self):
        g = self.game(hand=(SEA, FRIEND, 'count.install'), board=('sleep', 'card.1'), enemy=('card.2',))
        self.play(g, 'count.install')
        self.assertEqual((self.price(g), self.price(g, FRIEND)), (7, 4))
        self.assertEqual(tuple(map(len, self.fact(g).intrinsic.board_minions.boards)), (3, 1))
        self.portable(g)

    def test_summon_removal_and_control_change_requote_without_local_modifiers(self):
        g = self.game(hand=(SEA, FRIEND, 'count.summon', 'count.kill', 'count.control'),
            board=('card.1',), enemy=('card.2','card.3'))
        self.assertEqual((self.price(g), self.price(g, FRIEND)), (7, 5))
        self.play(g,'count.summon'); self.assertEqual((self.price(g),self.price(g,FRIEND)), (6,4))
        self.play(g,'count.kill'); self.assertEqual((self.price(g),self.price(g,FRIEND)), (7,5))
        self.play(g,'count.control'); self.assertEqual((self.price(g),self.price(g,FRIEND)), (7,4))
        e = self.source(g, SEA); self.assertEqual((e.base_cost, e.cost_modifier, e.enchantments), (10,0,[]))
        self.portable(g)

    def test_original_board_fact_remains_valid_after_real_board_changes(self):
        g = self.game(hand=(SEA,'count.summon'), board=('card.1',)); original = self.fact(g).intrinsic
        validate_intrinsic_origin(original,g.state,g.registry)
        self.play(g,'count.summon'); self.assertEqual(self.price(g),8)
        validate_intrinsic_history_prefix(original,g.state,g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(original,g.state,g.registry)

    def test_local_and_external_cost_layers_follow_the_continuous_intrinsic_stage(self):
        g = self.game(hand=(SEA,'count.local','count.external'), enemy=('card.1','card.2'))
        self.play(g,'count.local'); self.play(g,'count.external'); f = self.fact(g)
        self.assertEqual((f.intrinsic.base_cost,f.intrinsic.amount,f.local_amount,f.amount), (10,8,5,3))
        self.assertEqual(self.source(g,SEA).base_cost,10)
        self.play(g,SEA); self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana), (3,7))
        self.portable(g)

    def test_validation_enumeration_player_quote_and_payment_share_preentry_price(self):
        g = self.game(hand=(SEA,),board=('card.1',),enemy=('card.2',),mana=8)
        source = self.source(g,SEA); g.validate(PlayCard(1,source.id))
        port = g.for_player(1); dto = port.legal_actions(); ref = g.observe(1)['players'][0]['hand'][0]['ref']
        action = next(a for a in dto['actions'] if a.get('card') == ref)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'],8)
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        play = g.state.play_history[-1]; frozen = play.submitted_cost.quote.intrinsic.board_minions
        self.assertEqual((play.cost,g.state.players[1].mana,frozen.quantity),(8,0,2))
        self.assertNotIn(source.id, [r.entity_id for b in frozen.boards for r in b])
        self.assertEqual(sum(map(len,frozen.boards)),2); self.assertEqual(sum(len(p.board) for p in g.state.players.values()),3)
        self.portable(g)

    def test_insufficient_mana_does_not_pay_or_enter_and_zero_cost_can_be_played(self):
        g = self.game(hand=(SEA,),board=('card.1',),mana=8); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,SEA)
        self.assertEqual(g.snapshot(),before)
        g = self.game(hand=(FRIEND,),board=tuple(f'card.{i}' for i in range(1,7)),mana=0)
        self.play(g,FRIEND); self.assertEqual(g.state.play_history[-1].cost,0); self.portable(g)

    def test_generated_quotes_use_same_board_stage_without_allocating_a_subject(self):
        g=self.game(board=('card.1',),enemy=('card.2',));before=g.snapshot()
        f=capture_generated_quote_fact(g.state,g.registry,1,SEA)
        self.assertEqual((f.quote_input.base_cost,f.intrinsic.amount,f.amount),(10,8,8))
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,SEA).amount,self.price(g))
        self.assertEqual(g.snapshot(),before)

    def test_copy_silence_and_bounce_keep_printed_rule_and_reacquire_fresh_price(self):
        g=self.game(hand=('count.base','count.silence','count.bounce'),board=(SEA,),enemy=('card.1',))
        self.play(g,'count.base'); self.play(g,'count.silence'); self.play(g,'count.bounce')
        source=self.source(g,SEA)
        self.assertEqual((source.base_cost,self.price(g)),(10,8))
        self.assertEqual(g.registry.card(source.card_id).board_minion_cost,BoardMinionCostSpec('all'))
        self.portable(g)

    def test_card_played_wait_retains_original_count_and_restores_after_source_removal(self):
        g=self.game(hand=(SEA,),board=('card.1','count.watch'),enemy=('card.2',))
        self.play(g,SEA); play=g.state.play_history[-1]
        self.assertEqual((play.cost,play.submitted_cost.quote.intrinsic.board_minions.quantity),(7,3))
        self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        self.choose(g); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.play_history[-1].submitted_cost,play.submitted_cost)
        self.assertIsNotNone(g.state.play_history[-1].paid_hand_close); self.portable(g)

    def test_delayed_failure_restores_paid_receipt_board_allocator_and_rng(self):
        g=self.game(hand=(SEA,),board=('count.watch',))
        self.play(g,SEA);saved=self.portable(g);view=g.observe(1)
        with self.assertRaisesRegex(ResolutionError,'unknown.count.card'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.observe(1),view);self.portable(g)

    def test_complete_count_fact_rejects_duplicates_future_ids_unknown_and_inert_forgery(self):
        g=self.game(board=('card.1',),enemy=('card.2',)); stage=self.fact(g).intrinsic; board=stage.board_minions
        changes=(replace(board,boards=((board.boards[0][0],), (BoardMinionCostRow(board.boards[1][0].entity_id,'inert'),))),
            replace(board,boards=((board.boards[0][0],), (BoardMinionCostRow(board.boards[1][0].entity_id,'unknown'),))))
        for changed in changes:
            with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,replace(stage,board_minions=changed))
        for rows in ((board.boards[0],board.boards[0]), ((BoardMinionCostRow(board.next_entity_id,'card.1'),),board.boards[1])):
            with self.assertRaises(ValueError):replace(board,boards=rows)

    def test_friendly_scope_and_zero_amount_still_validate_unselected_unknown_rows(self):
        g=self.game(board=tuple(f'card.{i}' for i in range(1,8)),enemy=('card.8',));stage=self.fact(g,FRIEND).intrinsic
        board=stage.board_minions; self.assertEqual(stage.amount,0)
        changed=replace(board,boards=(board.boards[0],(BoardMinionCostRow(board.boards[1][0].entity_id,'unknown'),)))
        with self.assertRaisesRegex(ValueError,'unknown'):validate_intrinsic_stage_fact(g.registry,replace(stage,board_minions=changed))

    def test_physical_price_rejects_subject_allocated_after_captured_board(self):
        g=self.game(hand=(SEA,));f=self.fact(g);stage=f.intrinsic
        earlier=replace(stage.board_minions,next_entity_id=self.source(g,SEA).id)
        with self.assertRaisesRegex(ValueError,'newer than its captured allocator'):
            replace(f,intrinsic=replace(stage,board_minions=earlier))

    def test_rehashed_snapshot_cannot_omit_or_rewrite_complete_board_stage(self):
        g=self.game(hand=(SEA,),board=('card.1',),enemy=('card.2',));self.play(g,SEA);saved=self.portable(g)
        for edit in ('quantity','inert','duplicate','missing'):
            bad=deepcopy(saved);intrinsic=bad['state']['play_history'][0]['submitted_cost']['quote']['intrinsic'];board=intrinsic['board_minions']
            if edit=='quantity':board['quantity']+=1
            elif edit=='inert':board['boards'][0][0]['card_id']='inert'
            elif edit=='duplicate':board['boards'][1]=deepcopy(board['boards'][0])
            else:intrinsic['board_minions']=None
            with self.subTest(edit=edit),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_player_sees_own_quote_and_public_board_without_private_cost_proofs(self):
        g=self.game(hand=(SEA,),board=('card.1',),enemy=('card.2',),enemy_hand=(SEA,))
        own=g.observe(1);encoded=json.dumps(own)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'],8)
        self.assertEqual(own['players'][1]['hand'][0]['card_id'],None)
        for secret in ('board_minions','next_entity_id','IntrinsicCostStageFact','payment_state'):
            self.assertNotIn(secret,encoded)

    def test_default_empty_stage_and_new_strict_wire_keep_public_protocols(self):
        g=self.game(hand=('card.1',));f=self.fact(g,'card.1');self.assertIsNone(f.intrinsic.board_minions)
        self.play(g,'card.1');saved=self.portable(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,265))
        self.assertEqual((g.observe(1)['version'],g.for_player(1).observe()['version']),('player-view-v84','player-actions-v12'))
        for old in (1,169,170):
            bad=deepcopy(saved);bad['schema_version']=old
            with self.assertRaisesRegex(SnapshotError,'schemas 1 through 264'):Game.from_snapshot(bad,registry())

    def test_necessary_native_ticking_template_preserves_printed_sum_and_friendly_formula(self):
        r=native_registry();selected=ModularSelection('TOY_330',('TOY_330t98',modular_fixture.PERFECT),'TOY_330t5');cid=selected.card_id
        self.factory=native_registry
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(cid,),board=('card.1',),mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=('card.2','card.3'))),seed=7),r)
        self.assertEqual((r.card(cid).cost,r.card(cid).attack,r.card(cid).health),(9,4,5))
        self.assertEqual(self.price(g,cid),8);self.play(g,cid)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(8,2));self.portable(g)


if __name__ == '__main__': unittest.main()
