"""Timelord uses original printed editions and original physical dormancy."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.time_lord_nozdormu_card import CARD, BODY, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.dormancy import (AdvanceCapturedDormancy, AwakenMinion, MakeDormant)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, RequestChoice, Summon, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

P = 'timelord.test.'
NEW, SPELL, WEAPON, LOCATION, TOKEN = 'JAIL_202', 'CAP_006', 'JAIL_376', 'JAIL_877', 'JAIL_877t'
OLD = 'CORE_CS2_182'


@lru_cache(None)
def registry(mode=None):
    r = build_registry()
    def fail(c): raise ResolutionError('Timelord deliberate continuation failure')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'unknown', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition(P+'unknown', 'Unknown printed edition', CardType.SPELL,
        cost=1, on_play=P+'unknown'))
    if mode:
        event = ('minion_summoned' if mode.startswith('transform_') else
            'turn_ended' if mode in ('auto', 'summon') else
            'dormancy_progressed' if mode == 'after_wait' else 'card_played')
        def watch(c):
            if mode == 'auto':
                return (CastSpell(c.player_id, SPELL, c.source_id,
                    target_id=c.state.players[3-c.player_id].hero_id, targeting='explicit'),) if c.event.player_id==c.player_id else ()
            if mode == 'summon':
                return (Summon(c.player_id, NEW),) if c.event.player_id==c.player_id else ()
            if mode.startswith('transform_'):
                target = c.state.entities.get(c.event.target_id)
                original, result = (NEW, OLD) if mode == 'transform_new' else (OLD, NEW)
                if target is None or target.card_id != original: return ()
                return (Transform(target.id, result),)
            if c.event.player_id != c.player_id: return ()
            if mode == 'renew':
                target = next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
                return (AwakenMinion(target.id, c.source_id), MakeDormant(target.id, 5, c.source_id))
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', 'Observer', CardType.MINION, health=30,
            triggers=(TriggerSpec(event, P+'watch'),)))
    r.validate(); return r


class TimelordTests(unittest.TestCase):
    def game(self, hand=(), board=(CARD,), other_hand=(), other_board=(OLD,), mode=None, seat=1):
        own = PlayerSetup('HERO_08', hand=hand, board=(*((P+'watch',) if mode else ()), *board),
            deck=(OLD,)*8, mana=50, max_mana=50, mana_cap=50)
        other = PlayerSetup('HERO_08', hand=other_hand, board=other_board,
            deck=(OLD,)*8, mana=50, max_mana=50, mana_cap=50)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=278),registry(mode))

    def source(self, g, seat=1):
        return next(g.state.entities[i] for i in g.state.players[seat].board if g.state.entities[i].card_id==CARD)

    def play(self, g, cid, target=None):
        seat=g.state.active_player
        eid=next(i for i in g.state.players[seat].hand if g.state.entities[i].card_id==cid)
        card=g.registry.card(cid)
        if cid==SPELL and target is None:target=g.state.players[3-seat].hero_id
        g.apply(PlayCard(seat,eid,target_id=target,
            position=len(g.state.players[seat].board) if card.kind in (CardType.MINION,CardType.LOCATION) else None))
        return eid

    def choose(self, g, key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def cycle(self, g):
        g.apply(EndTurn(1));g.apply(EndTurn(2))

    def portable(self, g, mode=None):
        saved=json.loads(json.dumps(g.snapshot()));independent=registry.__wrapped__(mode)
        self.assertIsNot(independent,g.registry)
        other=Game.from_snapshot(saved,independent)
        self.assertEqual(saved,other.snapshot());self.assertEqual(saved,g.clone().snapshot())
        self.assertEqual(saved,replay(build_replay(g),registry.__wrapped__(mode)).snapshot())
        return other

    def test_a01_complete_root_two_native_enchant_sources_and_full_printed_inventory(self):
        data=load_batch();self.assertEqual(len(data['cards'])+len(data['evidence_only']),3)
        self.assertEqual(len(data['printed_card_sets']),23452)
        self.assertEqual(sum(x==1988 for x in data['printed_card_sets'].values()),332)
        for row in (*data['cards'],*data['evidence_only']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(data['latest_expansion']['name'],'逃离紫罗兰监狱')
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_a02_real_three_mana_eight_eight_dragon_enters_original_five_turn_dormancy(self):
        g=self.game(hand=(CARD,),board=());before=g.state.players[1].mana;eid=self.play(g,CARD)
        source=g.state.entities[eid]
        self.assertEqual((source.attack,source.max_health),(8,8));self.assertEqual(source.dormancy.remaining_turns,5)
        self.assertEqual(g.registry.card(CARD).metadata.tribes,('dragon',))
        self.assertEqual(g.state.players[1].mana,before-3)
        self.assertFalse(source.active);self.assertFalse(any(isinstance(a,Attack) and a.attacker_id==eid for a in g.legal_actions()))

    def test_a03_latest_minion_spell_weapon_and_location_plays_each_advance_once(self):
        g=self.game(hand=(NEW,SPELL,WEAPON,LOCATION))
        for remaining,cid in zip((4,3,2,1),(NEW,SPELL,WEAPON,LOCATION)):
            self.play(g,cid);self.assertEqual(self.source(g).dormancy.remaining_turns,remaining)
        self.assertEqual(len(g.state.play_history),4)

    def test_a04_miniset_prefix_and_noncollectible_derivative_use_actual_set_membership(self):
        g=self.game(hand=(SPELL,TOKEN))
        self.assertFalse(SPELL.startswith('JAIL_'));self.assertFalse(g.registry.card(TOKEN).metadata.collectible)
        self.play(g,SPELL);self.play(g,TOKEN)
        self.assertEqual(self.source(g).dormancy.remaining_turns,3)

    def test_a05_older_expansion_and_core_cards_do_not_advance(self):
        g=self.game(hand=(OLD,CARD))
        self.play(g,OLD);self.play(g,CARD)
        self.assertEqual([g.state.entities[i].dormancy.remaining_turns for i in g.state.players[1].board if g.state.entities[i].card_id==CARD],[5,5])

    def test_a06_opponent_latest_play_does_not_advance_my_countdown(self):
        g=self.game(other_hand=(SPELL,));g.apply(EndTurn(1));self.play(g,SPELL)
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_a07_countered_committed_latest_spell_still_counts_as_played(self):
        g=self.game(hand=(SPELL,),other_hand=('CORE_EX1_287',))
        g.apply(EndTurn(1));self.play(g,'CORE_EX1_287');g.apply(EndTurn(2))
        self.play(g,SPELL)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.source(g).dormancy.remaining_turns,3)

    def test_a08_automatic_cast_does_not_invent_a_hand_play_for_timelord(self):
        g=self.game(mode='auto');g.apply(EndTurn(1))
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(len(g.state.play_history),0)
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_a09_natural_summon_does_not_count_as_playing_latest_minion(self):
        g=self.game(mode='summon');g.apply(EndTurn(1))
        self.assertTrue(any(g.state.entities[i].card_id==NEW for i in g.state.players[1].board))
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_a10_original_latest_play_still_counts_after_physical_card_transforms_to_old_face(self):
        g=self.game(hand=(NEW,),mode='transform_new');eid=self.play(g,NEW)
        self.assertEqual(g.state.entities[eid].card_id,OLD)
        self.assertEqual(g.state.play_history[-1].card_id,NEW)
        self.assertEqual(self.source(g).dormancy.remaining_turns,4)

    def test_a11_original_old_play_does_not_count_after_transform_to_latest_face(self):
        g=self.game(hand=(OLD,),mode='transform_old');eid=self.play(g,OLD)
        self.assertEqual(g.state.entities[eid].card_id,NEW)
        self.assertEqual(g.state.play_history[-1].card_id,OLD)
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_a12_old_accepted_trigger_does_not_advance_replaced_dormancy(self):
        g=self.game(hand=(SPELL,),mode='renew');old=self.source(g).dormancy.id
        self.play(g,SPELL);source=self.source(g)
        self.assertNotEqual(source.dormancy.id,old);self.assertEqual(source.dormancy.remaining_turns,5)

    def test_a13_natural_owner_countdown_and_play_reduction_share_one_original_instance(self):
        g=self.game(hand=(SPELL,));dormancy=self.source(g).dormancy.id
        self.play(g,SPELL);self.cycle(g)
        self.assertEqual((self.source(g).dormancy.id,self.source(g).dormancy.remaining_turns),(dormancy,3))
        self.cycle(g);self.cycle(g);self.cycle(g)
        self.assertIsNone(self.source(g).dormancy)

    def test_a14_five_latest_plays_awaken_original_once_and_rush_only_attacks_minions(self):
        g=self.game(hand=(SPELL,)*5);eid=self.source(g).id
        for _ in range(5):self.play(g,SPELL)
        self.assertIsNone(self.source(g).dormancy);self.assertEqual(self.source(g).id,eid)
        self.assertEqual(len([e for e in g.events if e.kind=='minion_awakened' and e.target_id==eid]),1)
        actions=[a for a in g.legal_actions() if isinstance(a,Attack) and a.attacker_id==eid]
        self.assertTrue(actions);self.assertTrue(all(a.defender_id!=g.state.players[2].hero_id for a in actions))
        g.apply(actions[0]);self.assertEqual(g.state.entities[eid].attacks_this_turn,1)

    def test_a15_multiple_physical_timelords_each_reduce_once_per_real_play(self):
        g=self.game(hand=(SPELL,),board=(CARD,CARD));self.play(g,SPELL)
        self.assertEqual([g.state.entities[i].dormancy.remaining_turns for i in g.state.players[1].board],[4,4])

    def test_a16_full_board_awakes_in_place_without_an_extra_summon_or_allocation(self):
        g=self.game(hand=(SPELL,)*5,board=(CARD,*(OLD,)*6));eid=self.source(g).id
        for _ in range(5):self.play(g,SPELL)
        self.assertEqual(len(g.state.players[1].board),7);self.assertIsNone(g.state.entities[eid].dormancy)
        self.assertFalse(any(e.kind=='minion_summoned' for e in g.events))

    def test_a17_awake_native_source_stops_listening_to_later_plays(self):
        g=self.game(hand=(SPELL,)*6)
        for _ in range(5):self.play(g,SPELL)
        before=len([e for e in g.events if e.kind in ('dormancy_progressed','minion_awakened')])
        self.play(g,SPELL)
        self.assertEqual(len([e for e in g.events if e.kind in ('dormancy_progressed','minion_awakened')]),before)

    def test_a18_wait_before_native_callback_restores_independent_registry_clone_and_replay(self):
        g=self.game(hand=(SPELL,),mode='before_wait');self.play(g,SPELL)
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)
        other=self.portable(g,'before_wait')
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.source(g).dormancy.remaining_turns,4)

    def test_a19_wait_after_progress_keeps_exact_count_and_bad_resume_is_atomic(self):
        g=self.game(hand=(SPELL,),mode='after_wait');self.play(g,SPELL)
        self.assertEqual(self.source(g).dormancy.remaining_turns,4);saved=g.snapshot()
        self.portable(g,'after_wait')
        with self.assertRaisesRegex(ResolutionError,'Timelord deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g)

    def test_a20_unknown_original_edition_fails_explicitly_and_rolls_back_entire_play(self):
        g=self.game(hand=(P+'unknown',));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unreviewed original played-card edition'):self.play(g,P+'unknown')
        self.assertEqual(g.snapshot(),saved)

    def test_a21_unknown_opponent_edition_is_irrelevant_to_friendly_listener(self):
        g=self.game(other_hand=(P+'unknown',));g.apply(EndTurn(1));self.play(g,P+'unknown')
        self.assertEqual(self.source(g).dormancy.remaining_turns,5)

    def test_a22_captured_countdown_work_roundtrips_and_rejects_invalid_shapes(self):
        g=self.game();source=self.source(g)
        work=AdvanceCapturedDormancy(MinionReference.capture(source),source.dormancy.id,source_id=source.id)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g.events)
        self.assertEqual(codec.decode(codec.encode(work)),work)
        for values in ((work.reference,0,1),(work.reference,work.dormancy_id,True),(None,1,1)):
            with self.assertRaises(ValueError):AdvanceCapturedDormancy(*values)

    def test_a23_both_players_see_public_countdown_without_internal_source_or_inventory(self):
        g=self.game(hand=(SPELL,));self.play(g,SPELL)
        for seat in (1,2):
            wire=json.dumps(g.for_player(seat).observe())+json.dumps(g.player_events(seat))
            self.assertIn('remaining_turns',wire)
            for field in ('dormancy_id','printed_card_sets','AdvanceCapturedDormancy','resolution_frame','rng_state'):
                self.assertNotIn(chr(34)+field+chr(34),wire)

    def test_a24_second_seat_uses_own_play_and_countdown(self):
        g=self.game(hand=(SPELL,),seat=2);self.play(g,SPELL)
        self.assertEqual(self.source(g,2).dormancy.remaining_turns,4)
        self.portable(g)


if __name__=='__main__':unittest.main()
