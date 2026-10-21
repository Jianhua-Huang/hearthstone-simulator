"""Forge uses a real Location, exact non-cost armor and original deliveries."""
from functools import lru_cache
import json
import unittest
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.armor_summon_reward_card import CARD, TOKEN, load_batch
from hs_sim.engine import CardDefinition, CardType, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, UseLocation, Zone
from hs_sim.engine.armor_consumption import EVENT, PUBLIC_EVENT, SpendArmor, consumption_result
from hs_sim.engine.armor_gains import gained_this_turn
from hs_sim.engine.effects import AddCostModifier, ChangeControl, ChoiceOption, Destroy, GainArmor, InvokeBehavior, ReturnToHand, RequestChoice, Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import ModifyLocation, RefreshLocation
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, SummonQuantitySpec, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.zones import CardReference
from tools.card_batch import check_face

P = 'fixture.armor_summon.'
PLAIN, DOUBLE, SUMMON_WAIT, CONSUME_WAIT, GAIN_ON_ENTRY, FILL, CRASH, CHIP, REFRESH, FEE, RAW = (
    P+x for x in ('plain', 'double', 'summon_wait', 'consume_wait', 'gain_on_entry', 'fill', 'crash', 'chip', 'refresh', 'fee', 'raw'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COIN = 'GAME_005'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    def fail(c): raise ResolutionError('Explicit armor summon failure')
    r.register_behavior(P+'fail', fail)
    def reenter(c):
        e = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e), c.player_id),)
    r.register_behavior(P+'reenter', reenter)
    def wait(c):
        if c.event.kind == 'minion_summoned':
            target = c.event.target_id
            if c.state.entities[target].card_id != TOKEN: return ()
        else:
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != CARD: return ()
            target = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == TOKEN)
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ChoiceOption('gain', 'Gain later Armor', (GainArmor(c.player_id, 5),)),
            ChoiceOption('kill', 'Remove original', (Destroy(target, c.source_id),)),
            ChoiceOption('transform', 'Transform original', (Transform(target, PLAIN),)),
            ChoiceOption('give', 'Transfer original', (ChangeControl(target, 2),)),
            ChoiceOption('reenter', 'Leave and return', (ReturnToHand(target), InvokeBehavior(P+'reenter', c.source_id, c.player_id, target))),
            ChoiceOption('replace', 'Later same face', (Destroy(target, c.source_id),
                SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), SummonCause.capture(c)))),
        ), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_behavior(P+'entry_gain', lambda c: (GainArmor(c.player_id, 3),)
        if c.state.entities[c.event.target_id].card_id == TOKEN else ())
    r.register_behavior(P+'fill', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(PLAIN),), SummonCause.capture(c)),))
    for cid, event, body in ((SUMMON_WAIT, 'minion_summoned', P+'wait'),
            (CONSUME_WAIT, PUBLIC_EVENT, P+'wait'), (GAIN_ON_ENTRY, 'minion_summoned', P+'entry_gain'),
            (FILL, 'location_activated', P+'fill'), (CRASH, PUBLIC_EVENT, P+'fail')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec(event, body),), metadata=META))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=2, health=5, metadata=META))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=5,
        summon_quantities=(SummonQuantitySpec(),), metadata=META))
    for cid, body in {
        CHIP: lambda c: (ModifyLocation(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == CARD), -1, c.source_id),),
        REFRESH: lambda c: (RefreshLocation(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == CARD), c.source_id),),
        FEE: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1, card_types=(CardType.MINION,)),
            source_id=c.source_id, uses_remaining=1),),
        RAW: lambda c: (SpendArmor(c.player_id, 3, c.source_id),),
    }.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META))
    return r


class ArmorSummonRewardTests(unittest.TestCase):
    def game(self, armor=3, board=(CARD,), hand=(), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', armor=armor, board=board, hand=hand,
            deck=(COIN,)*8, mana=10, max_mana=10), PlayerSetup('HERO_08', board=enemy,
                deck=(COIN,)*8, mana=10, max_mana=10)), seed=2), fixture())

    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor
    def tokens(self, g): return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == TOKEN]
    def source(self, g): return next(i for i in g.state.players[1].board if g.state.entities[i].card_id == CARD)
    def use(self, g): g.apply(UseLocation(1, self.source(g)))
    def play(self, g, cid):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid)); return eid
    def choose(self, g, option):
        choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, (option,)))
    def results(self, g): return [x for e in g.events if (x := consumption_result(e)) is not None]

    def portable(self, g):
        saved = g.snapshot(); reader = fixture('reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), reader).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            view = g.for_player(player).observe()
            self.assertEqual(view['observation']['version'], 'player-view-v115')
            public = json.dumps(view)+json.dumps(g.player_events(player))
            for field in (EVENT, 'armor_summon_reward_accepted', '"resolution_frame"', '"rng_state"'):
                self.assertNotIn(field, public)

    def reject(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved, fixture('reader'))
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_complete_location_and_token_have_four_verified_primary_faces(self):
        data = load_batch(); rows = {x['record']['dbf_id']: x['record'] for x in data['cards']+data['dependencies']}
        self.assertTrue(data['dependency_primary_verified']); self.assertEqual(len(data['official_observations']), 4)
        for observation in data['official_observations']:
            check_face(rows[observation['face']['id']], observation['face'], observation['locale'])
        self.assertEqual((fixture().card(CARD).kind, fixture().card(CARD).cost, fixture().card(CARD).durability),
            (CardType.LOCATION, 3, 2))
        self.assertIn(Keyword.TAUNT, fixture().card(TOKEN).keywords)

    def test_placement_pays_mana_but_does_not_summon_or_spend_armor(self):
        g = self.game(board=(), hand=(CARD,)); self.play(g, CARD)
        self.assertEqual((g.state.players[1].mana, self.armor(g), len(self.tokens(g))), (7, 3, 0))
        self.assertFalse(self.results(g)); self.use(g)
        self.assertEqual((g.state.players[1].mana, self.armor(g)), (7, 0))
        self.assertEqual((self.tokens(g)[0].attack, self.tokens(g)[0].health), (6, 6))

    def test_full_threshold_never_spends_partial_armor(self):
        for balance in (0, 1, 2, 3, 5, 9):
            with self.subTest(balance=balance):
                g = self.game(balance); self.use(g); paid = 3 if balance >= 3 else 0
                self.assertEqual(self.armor(g), balance-paid)
                self.assertEqual((self.tokens(g)[0].attack, self.tokens(g)[0].health), (6, 6) if paid else (3, 3))
                row = self.results(g)[0]
                self.assertEqual((row.before, row.requested, row.actual, row.after), (balance, 3, paid, balance-paid))

    def test_only_original_delivery_is_buffed_among_same_face_minions(self):
        g = self.game(board=(TOKEN, CARD), enemy=(TOKEN,)); original = g.state.players[1].board[0]
        self.use(g)
        self.assertEqual((g.state.entities[original].attack, g.state.entities[original].health), (3, 3))
        self.assertEqual((self.tokens(g)[-1].attack, self.tokens(g)[-1].health), (6, 6))
        enemy = g.state.entities[g.state.players[2].board[0]]; self.assertEqual((enemy.attack, enemy.health), (3, 3))

    def test_quantity_extras_share_one_original_payment(self):
        g = self.game(6, board=(CARD, DOUBLE)); self.use(g)
        self.assertEqual(len(self.tokens(g)), 2)
        self.assertEqual([(e.attack, e.health) for e in self.tokens(g)], [(6, 6), (6, 6)])
        self.assertEqual((self.armor(g), len(self.results(g))), (3, 1))

    def test_full_board_use_is_rejected_before_durability_and_payment(self):
        g = self.game(board=(CARD,)+(PLAIN,)*6); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), saved)

    def test_last_durability_frees_slot_and_paid_wait_restores_original_source(self):
        g = self.game(board=(CARD, CONSUME_WAIT)+(PLAIN,)*5, hand=(CHIP,))
        self.play(g, CHIP); source = self.source(g); self.use(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual((self.armor(g), self.tokens(g)[0].attack), (0, 3)); self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit armor summon'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'continue')
        self.assertEqual((self.armor(g), self.tokens(g)[0].attack), (0, 6)); self.portable(g)

    def test_summon_reaction_gain_is_seen_before_payment(self):
        g = self.game(0, board=(CARD, GAIN_ON_ENTRY)); self.use(g)
        self.assertEqual((self.armor(g), self.tokens(g)[0].attack), (0, 6))
        self.assertEqual((self.results(g)[0].before, self.results(g)[0].actual), (3, 3))

    def test_before_payment_wait_and_later_gain_restore_full_group(self):
        g = self.game(0, board=(CARD, SUMMON_WAIT)); self.use(g)
        self.assertFalse(self.results(g)); self.portable(g)
        self.choose(g, 'gain')
        self.assertEqual((self.armor(g), self.tokens(g)[0].attack), (2, 6))
        self.assertEqual(len(self.results(g)), 1)

    def test_no_original_survivor_means_no_payment(self):
        g = self.game(board=(CARD, SUMMON_WAIT)); self.use(g); self.choose(g, 'kill')
        self.assertFalse(self.tokens(g)); self.assertEqual(self.armor(g), 3); self.assertFalse(self.results(g))

    def test_activation_reaction_can_fill_last_space_without_spending(self):
        g = self.game(board=(CARD, FILL)+(PLAIN,)*4); self.use(g)
        self.assertFalse(self.tokens(g)); self.assertEqual(self.armor(g), 3); self.assertFalse(self.results(g))

    def test_after_payment_continuous_transform_buffs_but_leave_or_control_change_does_not(self):
        for option in ('transform', 'reenter', 'give', 'replace'):
            with self.subTest(option=option):
                g = self.game(board=(CARD, CONSUME_WAIT)); self.use(g)
                original = self.tokens(g)[0].id; self.choose(g, option)
                self.assertEqual((self.armor(g), len(self.results(g))), (0, 1))
                if option == 'transform': self.assertEqual((g.state.entities[original].attack, g.state.entities[original].health), (5, 8))
                elif option == 'give': self.assertEqual((g.state.entities[original].controller, g.state.entities[original].attack), (2, 3))
                else: self.assertEqual([(e.attack, e.health) for e in self.tokens(g)], [(3, 3)])

    def test_later_armor_gain_does_not_reprice_or_repeat_original_debit(self):
        g = self.game(board=(CARD, CONSUME_WAIT)); self.use(g); self.choose(g, 'gain')
        self.assertEqual((self.armor(g), len(self.results(g)), self.tokens(g)[0].attack), (5, 1, 6))

    def test_whole_action_failure_rolls_back_original_debit_location_and_summon(self):
        g = self.game(board=(CARD, CRASH)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit armor summon'): self.use(g)
        self.assertEqual(g.snapshot(), saved)

    def test_effect_consumption_does_not_consume_card_price_modifier_or_create_gain(self):
        g = self.game(board=(), hand=(FEE, CARD, TOKEN)); self.play(g, FEE); self.play(g, CARD)
        uses = g.state.players[1].cost_modifiers[0].uses_remaining; costs = len(g.state.cost_use_history)
        self.use(g)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, uses)
        self.assertEqual(len(g.state.cost_use_history), costs); self.assertFalse(gained_this_turn(g.state, 1))
        self.assertEqual(len([e for e in g.events if e.kind == PUBLIC_EVENT]), 1)
        self.play(g, TOKEN); self.assertFalse(g.state.players[1].cost_modifiers)

    def test_two_uses_keep_separate_original_groups_and_payments(self):
        g = self.game(6, hand=(REFRESH,)); self.use(g); first = self.tokens(g)[0].id
        self.play(g, REFRESH); self.use(g)
        self.assertEqual((self.armor(g), len(self.results(g))), (0, 2))
        self.assertEqual([(e.attack, e.health) for e in self.tokens(g)], [(6, 6), (6, 6)])
        self.assertEqual(g.state.entities[first].attack, 6)

    def test_saved_amount_receipt_and_complete_recipient_plan_cannot_be_rewritten(self):
        g = self.game(board=(CARD, CONSUME_WAIT)); self.use(g); saved = g.snapshot()
        def dicts(x):
            if isinstance(x, dict):
                yield x
                for v in x.values(): yield from dicts(v)
            elif isinstance(x, list):
                for v in x: yield from dicts(v)
        for mutation in ('recipients', 'amount', 'receipt'):
            with self.subTest(mutation=mutation):
                edited = json.loads(json.dumps(saved))
                if mutation == 'receipt':
                    event = next(e for e in edited['events'] if e['kind'] == EVENT)
                    pairs = event['data']['result']; values = dict(pairs); values['before'] += 1; values['after'] += 1
                    event['data']['result'] = [[k, values[k]] for k, _ in pairs]
                else:
                    fields = next(n['fields'] for n in dicts(edited['resolution_frame'])
                        if isinstance(n.get('fields'), dict) and {'request','accepted','summon_ids','event_cursor','root_action_number'} <= set(n['fields']))
                    if mutation == 'recipients': fields['summon_ids']['tuple'] = []
                    else: fields['request']['fields']['amount'] = 4
                self.reject(edited)

    def test_standalone_exact_armor_consumption_is_not_partial_loss(self):
        for bank in (2, 3, 8):
            with self.subTest(bank=bank):
                g = self.game(bank, board=(), hand=(RAW,)); self.play(g, RAW)
                self.assertEqual(self.armor(g), bank-(3 if bank >= 3 else 0))
                self.assertFalse([e for e in g.events if e.kind in ('armor_lost', 'damage_dealt', 'armor_spent')])
