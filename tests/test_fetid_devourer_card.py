"""All real Fetid faces, held replacement and the original three-arrow batch."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.fetid_devourer_card import (CARD, COUNTS, FORMS, PROGRESS, load_batch,
    register_fetid_devourer_card)
from hs_sim.cards.noggenfogger_card import register_noggenfogger_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, DestroyBatch, InvokeBehavior,
    RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, Keyword, Rarity, Runes, TargetSpec, Zone
from hs_sim.engine.native_hand_targets import ACCEPTED
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from tools.card_batch import canonical, check_face

P = 'fixture.fetid.'
META = CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON)
ZERO, UNIT, STEALTH, IMMUNE, ELUSIVE, WATCH, ACQUIRE, AUTO, COPY, BASECOPY, BUFF, BOUNCE, NATURAL, UNKNOWN = (
    P+x for x in ('zero', 'unit', 'stealth', 'immune', 'elusive', 'watch', 'acquire', 'automatic',
        'copy', 'basecopy', 'buff', 'bounce', 'natural', 'unknown'))
MAYOR = 'CORE_CFM_670'
RUNE_ACQUIRE = P+'rune-acquire'
POOL = {3: P+'three', 6: P+'six', 9: P+'nine'}
CTX = GenerationContext('fixture.fetid-complete-pool', 'experimental')


def rune_card(runes): return P+'rune-'+''.join(map(str, runes))


@lru_cache(maxsize=None)
def fixture(mode='normal', pool='normal', role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_fetid_devourer_card(r)
    if MAYOR not in r.cards: register_noggenfogger_card(r)
    r.register_behavior(P+'noop', lambda c: ())
    for runes in FORMS:
        cid = rune_card(runes)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=P+'noop',
            metadata=CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON, runes=Runes(*runes))))
    for cid, keywords in ((UNIT, ()), (STEALTH, (Keyword.STEALTH,)), (IMMUNE, (Keyword.IMMUNE,)), (ELUSIVE, (Keyword.ELUSIVE,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=8, keywords=keywords, metadata=META))
    for cost, cid in POOL.items():
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=cost, health=5,
            metadata=CardMetadata(True, (CardClass.PRIEST,), Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.SPELL, on_play=P+'noop'))
    bodies = {
        ZERO: lambda c: (), ACQUIRE: lambda c: (AddToHand(c.player_id, CARD, c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='current', source_id=c.source_id),),
        BASECOPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='base', source_id=c.source_id),),
        BUFF: lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]), 2, 3, c.source_id, cost=CostSpec(delta=-2)),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),), NATURAL: lambda c: (Summon(c.player_id, CARD),),
    }
    from hs_sim.engine.spell_casts import CastSpell
    bodies[AUTO] = lambda c: (CastSpell(c.player_id, rune_card((3,0,0)), source_id=c.source_id),)
    bodies[RUNE_ACQUIRE] = lambda c: (AddToHand(c.player_id, CARD, c.source_id),
        RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id))
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        hand_arrow = cid in (COPY, BASECOPY, BUFF)
        metadata = CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON, runes=Runes(1,0,1)) if cid == RUNE_ACQUIRE else META
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata,
            targeting=TargetSpec(zones=(Zone.HAND if hand_arrow else Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly')
                if hand_arrow or cid == BOUNCE else None))
    def fail(c): raise ResolutionError('Deliberate Fetid reaction failure')
    r.register_behavior(P+'fail', fail)
    if mode != 'normal':
        event = {'wait_upgrade': 'hand_card_upgraded', 'fail_upgrade': 'hand_card_upgraded',
            'wait_death': 'minion_died', 'wait_draw': 'card_drawn', 'wait_summon': 'minion_summoned',
            'clear_offer': 'choice_requested', 'clear_all_offer': 'choice_requested'}[mode]
        def watch(c):
            if mode in ('clear_offer', 'clear_all_offer'):
                source = c.state.entities.get(c.event.source_id)
                if source is None or source.card_id != FORMS[(3,0,0)]: return ()
                ids = tuple(c.state.players[2].board)
                return (DestroyBatch(ids if mode == 'clear_all_offer' else ids[:2], c.source_id),)
            if mode == 'wait_summon' and c.state.entities[c.event.target_id].card_id not in POOL.values(): return ()
            if mode == 'fail_upgrade': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(3-c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, WATCH),)))
    members = tuple(POOL.values()) if pool != 'empty' else ()
    if pool == 'unknown':
        absent = P+'unknown-nine'
        r.register_pool_card(PoolCard(absent, CardType.MINION, 9, META, attack=2)); members = (*members, absent)
    r.register_pool(PoolDefinition('constructed.cards', 'v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class FetidTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), deck=None, mode='normal', pool='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(POOL[6],)*15 if deck is None else deck, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_01', hand=enemy_hand, board=enemy, deck=(UNIT,)*15, mana=40, max_mana=40, mana_cap=40)),
            seed=381, generation_context=CTX), fixture(mode, pool))
    def entity(self, g, cid, zone='hand', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None, pid=1):
        eid = self.entity(g, cid, pid=pid).id; g.apply(PlayCard(pid, eid, target)); return eid
    def choose(self, g, ids=None, key='ok'):
        q = g.state.pending_choice
        selected = (key,) if ids is None else tuple(o.id for i in ids for o in q.options if o.entity_id == i)
        return g.apply(SelectChoice(q.player_id, q.id, selected))
    def drain(self, g):
        while g.state.pending_choice is not None: self.choose(g)
    def portable(self, g, mode='normal', pool='normal'):
        other = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture(mode, pool, 'reader'))
        self.assertEqual(other.state_hash(), g.state_hash()); self.assertEqual(g.clone().state_hash(), g.state_hash())
        self.assertEqual(replay(build_replay(g), fixture(mode, pool, 'reader')).state_hash(), g.state_hash())
        return other
    def rehash(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_full_root_and_nineteen_original_faces_have_forty_complete_primary_observations(self):
        d = load_batch(); rows = {x['record']['id']: x for x in d['cards']+d['dependencies']}
        self.assertEqual(len(rows), 20); self.assertEqual(len(d['official_observations']), 40)
        for o in d['official_observations']: check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid, x in rows.items():
            self.assertEqual(canonical(x['record']), x['record_sha256'])
            card = fixture().card(cid)
            self.assertEqual((card.cost, card.attack, card.health), (7,9,6)); self.assertEqual(card.hand_progress, PROGRESS)
            self.assertEqual(set(card.metadata.tribes), {'undead','beast'})
        self.assertFalse(d['behavior_verified']); self.assertFalse(d['cn_calibrated'])

    def test_untransformed_real_body_pays_seven_without_a_battlecry(self):
        g = self.game(hand=(CARD,), enemy=(UNIT,)); eid = self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 33); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[eid].card_id, CARD); self.assertEqual(len(g.state.players[2].board), 1)
        self.portable(g)

    def test_each_complete_rune_set_selects_exactly_one_of_the_nineteen_real_faces(self):
        for runes, form in FORMS.items():
            with self.subTest(runes=runes):
                g = self.game(hand=(CARD, rune_card(runes))); eid = self.entity(g, CARD).id
                self.play(g, rune_card(runes)); self.assertEqual(g.state.entities[eid].card_id, form)
                self.assertEqual(len(g.state.play_history), 1); self.assertEqual(g.state.entities[eid].hand_entry_id, 1)

    def test_later_rune_play_replaces_the_whole_face_instead_of_stacking_or_rolling(self):
        g = self.game(hand=(CARD, rune_card((2,0,0)), rune_card((0,0,1)), rune_card((1,1,0))))
        eid = self.entity(g, CARD).id
        for runes in ((2,0,0), (0,0,1), (1,1,0)):
            self.play(g, rune_card(runes)); self.assertEqual(g.state.entities[eid].card_id, FORMS[runes])
        self.portable(g)

    def test_rune_less_cards_keep_the_current_face_and_same_face_play_does_not_reenter(self):
        g = self.game(hand=(CARD, rune_card((1,0,0)), ZERO, rune_card((1,0,0))))
        eid = self.entity(g, CARD).id; self.play(g, rune_card((1,0,0))); epoch = g.state.entities[eid].zone_epoch
        self.play(g, ZERO); self.play(g, rune_card((1,0,0)))
        self.assertEqual((g.state.entities[eid].card_id, g.state.entities[eid].zone_epoch), (FORMS[(1,0,0)], epoch))
        self.portable(g)

    def test_opponent_runes_and_unknown_opponent_metadata_do_not_change_the_owner(self):
        g = self.game(hand=(CARD,), enemy_hand=(rune_card((3,0,0)), UNKNOWN)); eid = self.entity(g, CARD).id
        g.apply(EndTurn(1)); self.play(g, rune_card((3,0,0)), pid=2); self.play(g, UNKNOWN, pid=2)
        self.assertEqual(g.state.entities[eid].card_id, CARD); self.portable(g)

    def test_unknown_own_original_rune_metadata_is_explicit_and_rolls_back(self):
        g = self.game(hand=(CARD, UNKNOWN)); before = g.state_hash()
        with self.assertRaisesRegex(ValueError, 'Rune metadata is unknown'): self.play(g, UNKNOWN)
        self.assertEqual(g.state_hash(), before)

    def test_past_plays_are_not_retroactive_but_a_card_in_hand_at_completion_can_react(self):
        g = self.game(hand=(rune_card((3,0,0)), ACQUIRE))
        self.play(g, rune_card((3,0,0))); self.play(g, ACQUIRE)
        self.assertEqual(self.entity(g, CARD).card_id, CARD)
        # A real native Rune minion can complete while a new copy is held.
        g = self.game(hand=(FORMS[(1,1,0)], CARD), enemy=(UNIT,))
        eid = self.entity(g, CARD).id; self.play(g, FORMS[(1,1,0)])
        self.choose(g, tuple(g.state.players[2].board))
        self.assertEqual(g.state.entities[eid].card_id, FORMS[(1,1,0)])
        self.portable(g)

    def test_effect_summons_and_automatic_casts_are_not_rune_hand_plays(self):
        g = self.game(hand=(CARD, AUTO, NATURAL)); eid = self.entity(g, CARD).id
        self.play(g, AUTO); self.play(g, NATURAL)
        self.assertEqual(g.state.entities[eid].card_id, CARD); self.assertEqual(len(g.state.play_history), 2)
        self.portable(g)

    def test_real_completed_spell_window_can_follow_a_choice_and_a_new_held_acquisition(self):
        g = self.game(hand=(RUNE_ACQUIRE,)); self.play(g, RUNE_ACQUIRE)
        self.assertEqual(self.entity(g, CARD).card_id, CARD); self.portable(g)
        paid_action = g.state.play_history[0].action
        self.choose(g)
        self.assertEqual(self.entity(g, FORMS[(1,0,1)]).card_id, FORMS[(1,0,1)])
        completed = next(e for e in g.events if e.kind == 'card_played')
        self.assertGreater(completed.action, paid_action); self.portable(g)

    def test_countered_completed_rune_hand_spell_still_changes_the_face(self):
        g = self.game(hand=(CARD, rune_card((3,0,0))), enemy_hand=('EX1_287',)); eid = self.entity(g, CARD).id
        g.apply(EndTurn(1)); self.play(g, 'EX1_287', pid=2); g.apply(EndTurn(2)); self.play(g, rune_card((3,0,0)))
        self.assertEqual(g.state.entities[eid].card_id, FORMS[(3,0,0)]); self.portable(g)

    def test_face_change_preserves_the_physical_card_current_buffs_and_local_cost(self):
        g = self.game(hand=(CARD, BUFF, rune_card((1,0,0)), rune_card((0,0,3))))
        eid = self.entity(g, CARD).id; self.play(g, BUFF, eid)
        for runes in ((1,0,0), (0,0,3)):
            self.play(g, rune_card(runes)); e = g.state.entities[eid]
            self.assertEqual((e.attack,e.health,quote_unselected_cost(g.state,g.registry,e).amount), (11,9,5))
        self.portable(g)

    def test_current_and_base_copies_keep_the_actual_form_with_independent_future_listeners(self):
        for copy in (COPY, BASECOPY):
            with self.subTest(copy=copy):
                g = self.game(hand=(CARD, rune_card((1,0,0)), copy, rune_card((0,1,0))))
                eid = self.entity(g, CARD).id; self.play(g, rune_card((1,0,0))); self.play(g, copy, eid)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand].count(FORMS[(1,0,0)]), 2)
                self.play(g, rune_card((0,1,0)))
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [FORMS[(0,1,0)]]*2)
                self.portable(g)

    def test_played_face_no_longer_reacts_on_board_and_bounce_reinstalls_its_native_listener(self):
        g = self.game(hand=(FORMS[(0,1,0)], BOUNCE, rune_card((3,0,0)), rune_card((0,0,1))))
        eid = self.play(g, FORMS[(0,1,0)]); self.play(g, rune_card((3,0,0)))
        self.assertEqual(g.state.entities[eid].card_id, FORMS[(0,1,0)])
        self.play(g, BOUNCE, eid); self.play(g, rune_card((0,0,1)))
        self.assertEqual(g.state.entities[eid].card_id, FORMS[(0,0,1)]); self.portable(g)

    def test_all_nineteen_real_battlecries_pay_once_and_execute_the_printed_complete_counts(self):
        for runes, form in FORMS.items():
            with self.subTest(runes=runes):
                blood, frost, unholy = runes
                g = self.game(hand=(form,), enemy=(UNIT,)*4)
                old_deck = len(g.state.players[1].deck); eid = self.play(g, form)
                if blood:
                    q = g.state.pending_choice; self.assertEqual((q.min_count,q.max_count), (blood,blood))
                    self.choose(g, tuple(g.state.players[2].board[:blood]))
                self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.players[1].mana, 33)
                self.assertEqual(len(g.state.players[2].board), 4-blood)
                self.assertEqual(len(g.state.players[1].deck), old_deck-frost)
                drawn = [g.state.entities[i] for i in g.state.players[1].hand]
                self.assertEqual(len(drawn), frost)
                for e in drawn: self.assertEqual(quote_unselected_cost(g.state,g.registry,e).amount, 3)
                others = [g.state.entities[i] for i in g.state.players[1].board if i != eid]
                self.assertEqual([e.card_id for e in others], [POOL[3*unholy]]*2 if unholy else [])
                self.assertEqual(len(g.state.play_history), 1)

    def test_three_blood_shortfall_and_target_protections_use_the_real_minion_arrow_domain(self):
        g = self.game(hand=(FORMS[(3,0,0)],), enemy=(UNIT, STEALTH, IMMUNE, ELUSIVE))
        self.play(g, FORMS[(3,0,0)]); q = g.state.pending_choice
        self.assertEqual((q.min_count,q.max_count), (2,2))
        self.assertEqual({o.card_id for o in q.options}, {UNIT, ELUSIVE})
        self.choose(g, tuple(o.entity_id for o in q.options))
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[2].board}, {STEALTH, IMMUNE})
        self.portable(g)

    def test_no_enemy_does_not_suppress_the_other_real_mixed_effects(self):
        g = self.game(hand=(FORMS[(1,1,1)],)); self.play(g, FORMS[(1,1,1)])
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board][1:], [POOL[3]]*2)
        self.portable(g)

    def test_frost_draws_actual_cards_and_fatigues_without_discounting_existing_hand(self):
        g = self.game(hand=(FORMS[(0,3,0)], POOL[6]), deck=()); self.play(g, FORMS[(0,3,0)])
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.health, 24); self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,POOL[6])).amount, 6)
        self.portable(g)

    def test_full_hand_burns_use_normal_capacity_and_only_real_arrivals_get_discounted(self):
        g = self.game(hand=(FORMS[(0,3,0)],)+(ZERO,)*9); self.play(g, FORMS[(0,3,0)])
        self.assertEqual(len(g.state.players[1].hand), 10)
        arrivals = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == POOL[6]]
        self.assertEqual(len(arrivals), 1); self.assertEqual(quote_unselected_cost(g.state,g.registry,arrivals[0]).amount, 3)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 2); self.portable(g)

    def test_unholy_full_board_empty_pool_and_unknown_eligible_are_not_silent_substitutions(self):
        form = FORMS[(0,0,3)]
        g = self.game(hand=(form,), board=(UNIT,)*6); self.play(g, form)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertFalse(g.state.successful_summon_history[1:])
        g = self.game(hand=(form,), pool='empty'); before = g._rng.getstate(); self.play(g, form)
        self.assertEqual(g._rng.getstate(), before); self.assertEqual(len(g.state.players[1].board), 1)
        self.portable(g, pool='empty')
        g = self.game(hand=(form,), pool='unknown'); before = g.state_hash()
        with self.assertRaisesRegex(ValueError, 'unknown-nine'): self.play(g, form)
        self.assertEqual(g.state_hash(), before)

    def test_three_arrows_are_saved_as_one_complete_choice_and_destroy_one_batch(self):
        g = self.game(hand=(FORMS[(3,0,0)],), enemy=(UNIT,)*4); self.play(g, FORMS[(3,0,0)])
        other = self.portable(g); ids = tuple(g.state.players[2].board[:3])
        self.choose(g, ids); self.choose(other, ids); self.assertEqual(other.state_hash(), g.state_hash())
        deaths = g.state.death_history; self.assertEqual(len(deaths), 3)
        self.assertEqual(len({d.batch for d in deaths}), 1); self.portable(g)

    def test_three_arrows_with_mayor_keep_three_distinct_actual_targets_and_local_rng_proof(self):
        g = self.game(hand=(FORMS[(3,0,0)],), board=(MAYOR,), enemy=(UNIT,)*4)
        self.play(g, FORMS[(3,0,0)]); self.choose(g, tuple(g.state.players[2].board[:3]))
        event = next(e for e in g.events if e.kind == ACCEPTED); data = dict(event.data)
        codec = FrameCodec(g.mechanics, g.registry)
        selections = (codec.decode(json.loads(data['selection'])), *codec.decode(json.loads(data['additional_selections'])))
        self.assertEqual(len(selections), 3); self.assertEqual(len({s.target_id for s in selections}), 3)
        self.assertEqual(len(g.state.players[2].board), 1); self.portable(g)

    def test_three_arrow_original_input_survives_a_one_or_zero_target_execution_subset(self):
        for mode in ('clear_offer','clear_all_offer'):
            with self.subTest(mode=mode):
                g = self.game(hand=(FORMS[(3,0,0)],), board=(MAYOR,WATCH), enemy=(UNIT,)*3, mode=mode)
                self.play(g, FORMS[(3,0,0)]); q = g.state.pending_choice
                self.assertEqual(q.min_count, 3); self.portable(g, mode=mode)
                self.choose(g, tuple(o.entity_id for o in q.options))
                self.assertFalse(g.state.players[2].board); self.portable(g, mode=mode)

    def test_three_arrow_invalid_duplicate_or_short_submission_keeps_the_original_waiting_state(self):
        g = self.game(hand=(FORMS[(3,0,0)],), enemy=(UNIT,)*4); self.play(g, FORMS[(3,0,0)])
        q = g.state.pending_choice; before = g.state_hash(); key = q.options[0].id
        for selected in ((key,), (key,key,key)):
            with self.assertRaises((IllegalAction,ValueError)): g.apply(SelectChoice(q.player_id,q.id,selected))
            self.assertEqual(g.state_hash(), before)

    def test_native_choice_extension_is_limited_to_three_board_arrows_and_one_hand_arrow(self):
        options = tuple(ChoiceOption(str(i), str(i)) for i in range(4))
        board = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')
        RequestChoice(1, options, 1, min_count=3, max_count=3, targeting=board)
        with self.assertRaises(ValueError): RequestChoice(1, options, 1, min_count=4, max_count=4, targeting=board)
        hand = TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly')
        with self.assertRaises(ValueError): RequestChoice(1, options, 1, min_count=3, max_count=3, targeting=hand)

    def test_real_three_target_player_command_uses_opaque_options_and_matches_direct_selection(self):
        g = self.game(hand=(FORMS[(3,0,0)],), enemy=(UNIT,)*4)
        self.play(g, FORMS[(3,0,0)]); other = self.portable(g)
        port = g.for_player(1); commands = port.legal_actions()
        command = next(c for c in commands['actions'] if c['type'] == 'select_choice')
        self.assertEqual(len(command['options']), 3)
        self.assertNotIn('target_facts', json.dumps(commands))
        q = g.state.pending_choice
        action = SelectChoice(1, q.id, tuple(q.options[int(o[1:])-1].id for o in command['options']))
        result = port.submit({'revision': commands['revision'], 'action': command})
        self.assertTrue(result['accepted']); other.apply(action)
        self.assertEqual(g.state_hash(), other.state_hash()); self.portable(g)

    def test_upgrade_and_mixed_death_draw_summon_reactions_restore_and_replay(self):
        for mode in ('wait_upgrade','wait_death','wait_draw','wait_summon'):
            with self.subTest(mode=mode):
                hand = (CARD, rune_card((1,1,1))) if mode == 'wait_upgrade' else (FORMS[(1,1,1)],)
                g = self.game(hand=hand, board=(WATCH,), enemy=(UNIT,), mode=mode)
                if mode == 'wait_upgrade': self.play(g, rune_card((1,1,1)))
                else:
                    self.play(g, FORMS[(1,1,1)]); self.choose(g, tuple(g.state.players[2].board))
                self.assertIsNotNone(g.state.pending_choice); self.portable(g, mode=mode)
                before = g.state_hash()
                with self.assertRaisesRegex(ResolutionError,'Deliberate'): self.choose(g, key='fail')
                self.assertEqual(g.state_hash(), before); self.drain(g); self.portable(g, mode=mode)

    def test_failed_face_reaction_rolls_back_face_history_rng_and_original_hand(self):
        g = self.game(hand=(CARD,rune_card((3,0,0))), board=(WATCH,), mode='fail_upgrade'); before = g.state_hash()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'): self.play(g, rune_card((3,0,0)))
        self.assertEqual(g.state_hash(), before)

    def test_three_arrow_request_tampering_is_rejected_after_outer_hashes_are_rebuilt(self):
        g = self.game(hand=(FORMS[(3,0,0)],), enemy=(UNIT,)*3); self.play(g, FORMS[(3,0,0)])
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertIsNotNone(saved['resolution_frame'])
        # Pending input counts are tied to the original typed native request.
        changed = deepcopy(saved); changed['state']['pending_choice']['min_count'] = 2
        self.rehash(changed)
        with self.assertRaises(SnapshotError): Game.from_snapshot(changed, fixture(role='reader'))

    def test_players_see_only_their_own_held_face_and_public_native_target_options(self):
        g = self.game(hand=(CARD,rune_card((1,1,1))), enemy_hand=(CARD,)); eid = self.entity(g,CARD).id
        self.play(g, rune_card((1,1,1)))
        own = json.dumps(g.observe(1)); other = json.dumps(g.observe(2))
        self.assertIn(FORMS[(1,1,1)], own); self.assertNotIn(FORMS[(1,1,1)], other)
        for viewer in (1,2):
            events = json.dumps(g.player_events(viewer))
            self.assertNotIn('progress_keys', events); self.assertNotIn('target_facts', events)
        self.assertEqual(g.state.entities[eid].card_id, FORMS[(1,1,1)])


if __name__ == '__main__': unittest.main()
