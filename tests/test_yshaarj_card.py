"""Real Y'Shaarj roots use original payments and ordinary finite skill recipes."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.yshaarj_card import (CARD, GAZE, MIGHT, SPAWN, DOMAIN, SKILLS,
    load_batch, register_yshaarj_card)
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHandAction,
    UseHeroPower, UseMinionAbility)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddCostModifier, Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, GainTemporaryMana, InvokeBehavior, RefreshMana, RequestChoice, Silence,
    SpendMana, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_history import EVENT as HAND_ENTERED
from hs_sim.engine.model import (CardClass, CardMetadata, CostSpec, DamageKind, HandActionSpec,
    PaymentType, Rarity, SummonQuantitySpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import canonical, check_face

P = 'fixture.yshaarj.'
A, B, CHEAP, PLAIN, PAY20, PAY19, PAY30, HEALTH, PREP, ZERO, BIGSPELL, KILLER, DORMANT, DOUBLE, WATCH, UNKNOWN = (
    P+x for x in ('eight', 'nine_priest', 'seven', 'plain', 'pay20', 'pay19', 'pay30', 'health',
        'prepare', 'zero', 'bigspell', 'killer', 'dormant', 'double', 'watch', 'unknown'))
HURT, QUIET, MORPH, TAKE, DISCOUNT, REFRESH, CONSUME, TEMP, NATURAL, AGAIN = (
    P+x for x in ('hurt', 'quiet', 'morph', 'take', 'discount', 'refresh', 'consume', 'temp', 'natural', 'again'))
CTX = GenerationContext('fixture.yshaarj', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON)


@lru_cache(maxsize=None)
def fixture(mode=None, pool='normal', role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_yshaarj_card(r)
    for cid, cost, attack, health in ((A, 8, 2, 10), (B, 9, 4, 12), (CHEAP, 7, 1, 30),
            (PLAIN, 0, 1, 40), (PAY20, 20, 2, 40), (PAY19, 19, 2, 40), (PAY30, 30, 2, 40),
            (HEALTH, 20, 2, 40), (PREP, 12, 2, 40), (ZERO, 0, 1, 40),
            (KILLER, 0, 20, 20), (DORMANT, 0, 7, 30), (DOUBLE, 0, 1, 40)):
        kwargs = {}
        if cid == HEALTH: kwargs['cost_payment'] = PaymentType.HEALTH
        if cid == PREP: kwargs['hand_actions'] = (HandActionSpec('prepare', 'prepare', 1),)
        if cid == DORMANT: kwargs['dormant_turns'] = 1
        if cid == DOUBLE: kwargs['summon_quantities'] = (SummonQuantitySpec(2, (CardType.MINION,)),)
        meta = CardMetadata(True, (CardClass.PRIEST,), Rarity.COMMON) if cid == B else META
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=attack, health=health,
            metadata=meta, **kwargs))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    bodies = {HURT: lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),),
        QUIET: lambda c: (Silence(c.target_id),), MORPH: lambda c: (Transform(c.target_id, PLAIN),),
        TAKE: lambda c: (ChangeControl(c.target_id, 3-c.state.entities[c.target_id].controller),),
        DISCOUNT: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-5, card_ids=(CARD,)), source_id=c.source_id),),
        REFRESH: lambda c: (RefreshMana(c.player_id, 80),),
        CONSUME: lambda c: (SpendMana(c.player_id, 30, c.source_id),),
        TEMP: lambda c: (GainTemporaryMana(c.player_id, 20),),
        NATURAL: lambda c: (Summon(c.player_id, CARD),),
        AGAIN: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),),
        BIGSPELL: lambda c: ()}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=30 if cid == BIGSPELL else 0,
            requires_target=cid in (HURT, QUIET, MORPH, TAKE, AGAIN), on_play=cid, metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def fail(c): raise ResolutionError('Deliberate Yshaarj continuation failure')
    r.register_behavior(P+'fail', fail)
    if mode:
        def watch(c):
            target = c.state.entities.get(c.event.target_id)
            if target is None or target.card_id not in ((CARD,) if mode == 'wait_grant' else (A, B)): return ()
            if mode == 'kill': return (Destroy(target.id, c.source_id),)
            if mode == 'transform': return (Transform(target.id, PLAIN),)
            if mode == 'give': return (ChangeControl(target.id, 2),)
            if mode == 'buff': return (Buff(target.id, 5, 5, c.source_id),)
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(3-c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(WATCH, watch)
        event = 'ability_granted' if mode == 'wait_grant' else HAND_ENTERED if mode == 'wait_hand' else 'minion_summoned'
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
            triggers=(TriggerSpec(event, WATCH),)))
    members = () if pool == 'empty' else (A, B, CHEAP, BIGSPELL)
    if pool == 'foreign': members = (B, CHEAP, BIGSPELL)
    if pool == 'unknown':
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 8, META, attack=2))
        members = (*members, UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards', 'v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class YshaarjSourceTests(unittest.TestCase):
    def parent(self):
        pack = load_batch(); raw = pack['cards'][0]['record']
        return raw, [o for o in pack['official_observations'] if o['card_id'] == CARD]

    def test_all_five_complete_records_and_ten_primary_faces_keep_original_forms(self):
        pack = load_batch(); before = deepcopy(pack)
        rows = {x['record']['id']: x['record'] for x in pack['cards']+pack['dependencies']}
        self.assertEqual(len(pack['official_observations']), 10)
        for o in pack['official_observations']:
            raw = rows[o['card_id']]
            check_face(raw, o['face'], o['locale'], {'{0}': '30'} if raw['id'] == CARD else None,
                numeric_normalizations={'cost': 0} if raw['cost'] is None else None)
            self.assertEqual(canonical(raw), next(x['record_sha256'] for x in pack['cards']+pack['dependencies']
                if x['record']['id'] == raw['id']))
        self.assertEqual(pack, before); self.assertEqual(len(rows[CARD]['text'].split('@')), 3)
        self.assertTrue(all(fixture().card(cid).choice_only for cid in SKILLS))

    def test_pinned_progress_cannot_drop_or_change_any_complete_body_or_primary_rule(self):
        raw, observations = self.parent()
        for o in observations:
            key = 'text' if o['locale'] == 'zh_CN' else 'text_en'
            for index in (0, 1, 2):
                changed = deepcopy(raw); forms = changed[key].split('@'); forms[index] = forms[index].replace('30', '29')
                changed[key] = '@'.join(forms)
                with self.subTest(locale=o['locale'], index=index), self.assertRaises(ValueError):
                    check_face(changed, o['face'], o['locale'], {'{0}': '30'})
            for text in (o['face']['text'].replace('30', '29'),
                    o['face']['text'].split('<i>')[0],
                    o['face']['text'].replace('随从牌', '法术牌').replace('minions', 'spells')):
                with self.assertRaises(ValueError): check_face(raw, dict(o['face'], text=text), o['locale'], {'{0}': '30'})
            for declaration in (None, {'{0}': ''}, {'{0}': '29'}, {'@': '', '{0}': '30'}):
                with self.assertRaises(ValueError): check_face(raw, o['face'], o['locale'], declaration)

    def test_progress_display_still_requires_all_primary_numeric_typed_and_identity_fields(self):
        raw, observations = self.parent()
        for o in observations:
            for key, value in (('id', 1), ('manaCost', 9), ('attack', 9), ('health', 9), ('cardTypeId', 5),
                    ('classId', 9), ('cardSetId', 1), ('collectible', False), ('name', 'Another Old God')):
                with self.subTest(locale=o['locale'], field=key), self.assertRaises(ValueError):
                    check_face(raw, dict(o['face'], **{key: value}), o['locale'], {'{0}': '30'})


class YshaarjTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode=None, pool='normal', mana=80):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(PLAIN,)*12, mana=mana, max_mana=mana, mana_cap=80,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_01', hand=enemy_hand, board=enemy, deck=(PLAIN,)*12, mana=80, max_mana=80, mana_cap=80)),
            seed=179, generation_context=CTX), fixture(mode, pool))

    def first(self, g, cid, zone='board', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        source = self.first(g, cid, 'hand', player)
        g.apply(PlayCard(player, source.id, target)); return source.id

    def use(self, g, skill): return g.apply(UseMinionAbility(1, self.first(g, CARD).id, skill))
    def immune(self, g): return Keyword.IMMUNE in self.first(g, CARD).keywords
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def cost(self, g, cid): return quote_unselected_cost(g.state, g.registry, self.first(g, cid, 'hand')).amount

    def portable(self, g, mode=None, pool='normal'):
        other = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture(mode, pool, 'reader'))
        self.assertEqual(other.state_hash(), g.state_hash()); self.assertEqual(g.clone().state_hash(), g.state_hash())
        self.assertEqual(replay(build_replay(g), fixture(mode, pool, 'reader')).state_hash(), g.state_hash())
        return other

    def test_current_minion_payment_counts_toward_exact_thirty_mana_condition(self):
        g = self.game(hand=(PAY20, CARD)); self.play(g, PAY20); source = self.play(g, CARD)
        self.assertTrue(self.immune(g)); self.assertEqual(g.state.players[1].mana, 50)
        self.assertEqual([(p.cost, p.payment) for p in g.state.play_history], [(20, PaymentType.MANA), (10, PaymentType.MANA)])
        flag, = [a for a in g.state.entities[source].abilities if a.timed_keyword]
        self.assertEqual((flag.keyword_expiry.player_id, flag.keyword_expiry.boundary), (1, 'turn_started'))
        self.portable(g)

    def test_twenty_nine_and_real_discounted_payments_do_not_use_printed_mana(self):
        g = self.game(hand=(PAY19, CARD)); self.play(g, PAY19); self.play(g, CARD); self.assertFalse(self.immune(g))
        g = self.game(hand=(PAY20, DISCOUNT, CARD)); self.play(g, PAY20); self.play(g, DISCOUNT); self.play(g, CARD)
        self.assertEqual(g.state.play_history[-1].cost, 5); self.assertFalse(self.immune(g))

    def test_health_payment_and_expensive_spells_are_not_mana_spent_on_minions(self):
        for cid in (HEALTH, BIGSPELL):
            with self.subTest(card=cid):
                g = self.game(hand=(cid, CARD)); self.play(g, cid); self.play(g, CARD)
                self.assertFalse(self.immune(g))

    def test_explicit_consumption_refresh_power_and_prepare_are_not_minion_play_debits(self):
        g = self.game(hand=(CONSUME, REFRESH, CARD)); self.play(g, CONSUME); self.play(g, REFRESH); self.play(g, CARD)
        self.assertFalse(self.immune(g)); self.assertEqual(g.state.mana_consumption_history[0].actual, 30)
        g = self.game(hand=(PAY19, PREP, CARD)); self.play(g, PAY19)
        g.apply(UseHandAction(1, self.first(g, PREP, 'hand').id, 'prepare'))
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id)); self.play(g, CARD)
        self.assertFalse(self.immune(g)); self.assertEqual(len(g.state.play_history), 2)

    def test_temporary_mana_counts_and_later_transform_does_not_rewrite_original_payments(self):
        g = self.game(hand=(TEMP, PAY20, MORPH, CARD), mana=10); self.play(g, TEMP)
        paid = self.play(g, PAY20); self.play(g, MORPH, paid); self.play(g, CARD)
        self.assertTrue(self.immune(g)); self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.state.play_history[1].card_id, PAY20)

    def test_opponent_minion_spending_does_not_satisfy_own_condition(self):
        g = self.game(hand=(CARD,), enemy_hand=(PAY30,)); g.apply(EndTurn(1)); self.play(g, PAY30, player=2)
        g.apply(EndTurn(2)); self.play(g, CARD); self.assertFalse(self.immune(g))

    def test_natural_summon_has_no_battlecry_but_indirect_battlecry_uses_current_game_total(self):
        g = self.game(hand=(PAY30, NATURAL, AGAIN)); self.play(g, PAY30); self.play(g, NATURAL)
        self.assertFalse(self.immune(g)); before = g.state.players[1].mana
        self.play(g, AGAIN, self.first(g, CARD).id); self.assertTrue(self.immune(g))
        self.assertEqual(g.state.players[1].mana, before); self.assertEqual(len(g.state.battlecry_history), 1)

    def test_immunity_spans_opponent_turn_and_expires_at_original_next_own_start(self):
        g = self.game(hand=(PAY20, CARD)); self.play(g, PAY20); self.play(g, CARD)
        g.apply(EndTurn(1)); self.assertTrue(self.immune(g)); self.portable(g)
        g.apply(EndTurn(2)); self.assertFalse(self.immune(g)); self.portable(g)

    def test_immunity_is_silenceable_and_control_transfer_keeps_original_clock(self):
        g = self.game(hand=(PAY20, CARD, QUIET)); self.play(g, PAY20); self.play(g, CARD)
        self.play(g, QUIET, self.first(g, CARD).id); self.assertFalse(self.immune(g))
        g = self.game(hand=(PAY20, CARD, TAKE)); self.play(g, PAY20); source = self.play(g, CARD); self.play(g, TAKE, source)
        g.apply(EndTurn(1)); self.assertIn(Keyword.IMMUNE, g.state.entities[source].keywords)
        g.apply(EndTurn(2)); self.assertNotIn(Keyword.IMMUNE, g.state.entities[source].keywords)

    def test_gaze_forces_every_actual_enemy_in_order_without_spending_their_attack_budget(self):
        g = self.game(board=(CARD,), enemy=(A, B)); self.use(g, GAZE)
        self.assertEqual(self.first(g, CARD).health, 4); self.assertEqual(self.first(g, B, player=2).health, 2)
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.assertTrue(all(x.declaration.forced for x in g.state.character_attack_history))
        self.assertEqual(self.first(g, B, player=2).attacks_this_turn, 0); self.assertFalse(g.state.cast_history)
        self.portable(g)

    def test_gaze_can_force_enemies_into_the_immune_actual_source(self):
        g = self.game(hand=(PAY20, CARD), enemy=(A, B)); self.play(g, PAY20); self.play(g, CARD); self.use(g, GAZE)
        self.assertEqual(self.first(g, CARD).health, 10); self.assertTrue(self.immune(g))
        self.assertEqual(self.first(g, B, player=2).health, 2)

    def test_gaze_stops_hitting_a_departed_source_and_empty_board_does_not_sample(self):
        g = self.game(board=(CARD,), enemy=(KILLER, B)); source = self.first(g, CARD).id; self.use(g, GAZE)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertEqual(self.first(g, B, player=2).health, 12)
        g = self.game(board=(CARD,)); before = g.snapshot()['rng_state']; self.use(g, GAZE)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_might_adds_only_immediate_neighbors_current_attack_and_remaining_health(self):
        g = self.game(board=(A, CARD, B), hand=(HURT,)); self.play(g, HURT, self.first(g, A).id); self.use(g, MIGHT)
        self.assertEqual((self.first(g, CARD).attack, self.first(g, CARD).health), (16, 29))
        self.assertEqual(self.first(g, A).health, 7); self.assertEqual(self.first(g, B).health, 12)
        self.portable(g)

    def test_might_empty_edge_and_dormant_neighbor_keep_the_actual_slots(self):
        g = self.game(board=(CARD, DORMANT, A)); self.use(g, MIGHT)
        self.assertEqual((self.first(g, CARD).attack, self.first(g, CARD).health), (10, 10))
        g = self.game(board=(CARD, B, A)); self.use(g, MIGHT)
        self.assertEqual((self.first(g, CARD).attack, self.first(g, CARD).health), (14, 22))

    def test_spawn_uses_complete_all_class_minion_pool_at_least_eight_and_gets_matching_base_copy(self):
        g = self.game(board=(CARD,), pool='foreign'); self.use(g, SPAWN)
        self.assertEqual(self.first(g, B).card_id, B); copy = self.first(g, B, 'hand')
        self.assertEqual((copy.attack, copy.health), (4, 12)); self.assertEqual(self.cost(g, B), 9)
        self.assertEqual(len(g.state.successful_summon_history), 1); self.assertFalse(g.state.cast_history)
        self.portable(g, pool='foreign')

    def test_spawn_original_delivery_still_gets_original_face_after_death_transform_transfer_or_buff(self):
        for mode in ('kill', 'transform', 'give', 'buff'):
            with self.subTest(mode=mode):
                g = self.game(board=(CARD, WATCH), mode=mode, pool='foreign'); self.use(g, SPAWN)
                copy = self.first(g, B, 'hand'); self.assertEqual((copy.attack, copy.health), (4, 12))
                self.assertEqual(self.cost(g, B), 9)

    def test_spawn_quantity_extras_each_get_a_copy_and_full_board_has_no_delivery_or_rng(self):
        g = self.game(board=(CARD, DOUBLE), pool='foreign'); self.use(g, SPAWN)
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id == B]), 2)
        g = self.game(board=(CARD,)+(PLAIN,)*6); before = g.snapshot()['rng_state']; self.use(g, SPAWN)
        self.assertFalse(g.state.players[1].hand); self.assertFalse(g.state.successful_summon_history)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_spawn_full_hand_burns_only_copy_and_empty_pool_does_not_sample(self):
        g = self.game(board=(CARD,), hand=(PLAIN,)*10, pool='foreign'); self.use(g, SPAWN)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(self.first(g, B).card_id, B)
        g = self.game(board=(CARD,), pool='empty'); before = g.snapshot()['rng_state']; self.use(g, SPAWN)
        self.assertFalse(g.state.players[1].hand); self.assertEqual(g.snapshot()['rng_state'], before)

    def test_unknown_eligible_spawn_rolls_back_without_pruning_or_consuming_native_skill(self):
        g = self.game(board=(CARD,), pool='unknown'); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g, SPAWN)
        self.assertEqual(g.state_hash(), before)

    def test_domain_lasts_across_turns_reduces_next_card_once_and_does_not_reduce_power(self):
        g = self.game(board=(CARD,), hand=(PAY20, PAY19)); self.use(g, DOMAIN)
        self.assertEqual(self.cost(g, PAY20), 15)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(self.cost(g, PAY20), 15); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.cost(g, PAY20), 15); self.play(g, PAY20)
        self.assertEqual(g.state.play_history[-1].cost, 15); self.assertEqual(self.cost(g, PAY19), 19)
        self.portable(g)

    def test_domain_is_consumed_by_zero_cost_card_and_survives_source_control_change(self):
        g = self.game(board=(CARD,), hand=(ZERO, PAY20)); self.use(g, DOMAIN); self.play(g, ZERO)
        self.assertEqual(self.cost(g, PAY20), 20)
        g = self.game(board=(CARD,), hand=(PAY20,), enemy_hand=(TAKE,)); self.use(g, DOMAIN)
        source = self.first(g, CARD).id; g.apply(EndTurn(1)); self.play(g, TAKE, source, player=2)
        self.assertEqual(self.cost(g, PAY20), 15); self.assertEqual(g.state.entities[source].controller, 2)
        self.assertEqual(len(g.state.players[2].cost_modifiers), 0)

    def test_original_immunity_grant_wait_restores_and_completes_without_another_payment(self):
        g = self.game(hand=(PAY20, CARD), board=(WATCH,), mode='wait_grant'); self.play(g, PAY20); self.play(g, CARD)
        self.assertIsNotNone(g.state.pending_choice); other = self.portable(g, 'wait_grant')
        for branch in (g, other): self.choose(branch)
        self.assertEqual(g.state_hash(), other.state_hash()); self.assertEqual(g.state.players[1].mana, 50)

    def test_spawn_entry_and_hand_waits_restore_then_deliver_each_copy_exactly_once(self):
        for mode in ('wait_summon', 'wait_hand'):
            with self.subTest(mode=mode):
                g = self.game(board=(CARD, WATCH), mode=mode, pool='foreign'); self.use(g, SPAWN)
                self.assertIsNotNone(g.state.pending_choice); other = self.portable(g, mode, 'foreign')
                for branch in (g, other):
                    while branch.state.pending_choice: self.choose(branch)
                self.assertEqual(g.state_hash(), other.state_hash()); self.assertEqual(len(g.state.players[1].hand), 1)
                self.portable(g, mode, 'foreign')

    def test_failed_entry_and_bad_resume_roll_back_rng_delivery_copy_and_native_usage(self):
        g = self.game(board=(CARD, WATCH), mode='fail'); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g, SPAWN)
        self.assertEqual(g.state_hash(), before)
        g = self.game(board=(CARD, WATCH), mode='wait_summon'); self.use(g, SPAWN); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.state_hash(), before)

    def test_rehashed_payment_facts_cannot_be_replaced_to_forge_condition(self):
        g = self.game(hand=(PAY20, CARD)); self.play(g, PAY20); self.play(g, CARD)
        saved = deepcopy(g.snapshot()); saved['state']['play_history'][0]['cost'] = 19
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture(role='reader'))

    def test_both_player_views_hide_payment_histories_and_pool_and_expiry_proofs(self):
        g = self.game(hand=(PAY20, CARD)); self.play(g, PAY20); self.play(g, CARD); self.use(g, SPAWN)
        for pid in (1, 2):
            public = json.dumps(g.observe(pid))+json.dumps(g.for_player(pid).legal_actions())
            for key in ('play_history', 'cost_use_history', 'pool_basis', 'keyword_expiry', 'card_summon_history'):
                self.assertNotIn('"'+key+'"', public)
        self.portable(g)
