"""Actual enemy Bonus Effects theft and the shared attachment lifecycle."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.violet_tormentor_card import CARD, BODY, load_batch, register_violet_tormentor_card
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS, StealBonusEffects, bonus_candidates
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, Destroy, GrantKeyword,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import BoardPresenceReference, KeywordAuraSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest

P = 'violet.test.'
ALL, FILL, ODD, HIDDEN, DORMANT, AURA, WATCH = (P+x for x in ('all','fill','odd','hidden','dormant','aura','watch'))
HIT, SILENCE, COPY, BASE = (P+x for x in ('hit','silence','copy','base'))


def registry(mode=None):
    r = Registry('violet-punisher-native-tests-v1.'+str(mode))
    register_violet_tormentor_card(r)
    r.register_card(CardDefinition(P+'hero', 'Hero', CardType.HERO, health=100))
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(ALL, ALL, CardType.MINION, attack=2, health=20, keywords=BONUS_EFFECTS))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=2, health=20))
    r.register_card(CardDefinition(ODD, ODD, CardType.MINION, attack=2, health=20,
        keywords=(Keyword.CHARGE,), deathrattle=P+'noop', spell_damage=3))
    r.register_card(CardDefinition(HIDDEN, HIDDEN, CardType.MINION, health=20, keywords=(Keyword.STEALTH,)))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, health=20, dormant_turns=2))
    r.register_card(CardDefinition(AURA, AURA, CardType.MINION, health=20,
        keyword_auras=(KeywordAuraSpec(Keyword.TAUNT, 'friendly_minions'),)))
    def copied(c, kind):
        return (CopyMinion(BoardPresenceReference.capture(c.state, c.target_id), c.player_id,
            mode=kind, cause=SummonCause.capture(c)),)
    for cid, body in ((SILENCE, lambda c: (Silence(c.target_id),)),
                      (COPY, lambda c: copied(c, 'current')), (BASE, lambda c: copied(c, 'base'))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.register_behavior(HIT, lambda c: (Damage(c.state.players[3-c.player_id].board[0], 1, c.source_id),))
    r.register_card(CardDefinition(HIT, HIT, CardType.SPELL, on_play=HIT))
    def fail(c):
        raise ResolutionError('Violet deliberate reaction failure')
    r.register_behavior(P+'fail', fail)
    def watch(c):
        event = c.event
        if mode == 'duplicate':
            e = c.state.entities.get(event.target_id)
            if e is None or e.card_id != CARD:
                return ()
            victim = c.state.players[3-e.controller].board[0]
            return (GrantKeyword(victim, Keyword.TAUNT, c.source_id),
                    GrantKeyword(e.id, Keyword.TAUNT, c.source_id))
        if mode == 'entry':
            e = c.state.entities.get(event.target_id)
            if e is None or e.card_id != CARD:
                return ()
            source, victim = e.id, c.state.players[3-e.controller].board[0]
        elif mode == 'grant':
            e = c.state.entities.get(event.target_id)
            if (e is None or e.card_id != CARD or
                    sum(a.kind == 'keyword' and not a.consumed for a in e.abilities) != 1):
                return ()
            source, victim = e.id, c.state.players[3-e.controller].board[0]
        else:
            source, victim = event.source_id, event.target_id
        if mode == 'fail':
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ChoiceOption('bounce_target', 'Return original target', (ReturnToHand(victim),)),
            ChoiceOption('bounce_source', 'Return original source', (ReturnToHand(source),)),
            ChoiceOption('silence_target', 'Silence original target', (Silence(victim),)),
            ChoiceOption('kill_source', 'Destroy original source', (Destroy(source, c.source_id),)),
        ), c.source_id),)
    r.register_behavior(P+'watch', watch)
    event = 'minion_summoned' if mode in ('entry','duplicate') else 'ability_granted' if mode == 'grant' else 'bonus_effects_stolen'
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=50,
        triggers=(TriggerSpec(event, P+'watch'),)))
    r.validate()
    return r


class VioletPunisherTests(unittest.TestCase):
    def game(self, enemy=(ALL,), mode=None, pid=1):
        self.mode = mode
        actor = PlayerSetup(P+'hero', deck=(FILL,)*6, hand=(CARD,HIT,SILENCE,COPY,BASE),
            board=(WATCH,) if mode else (), max_mana=20, mana=20, mana_cap=20)
        other = PlayerSetup(P+'hero', deck=(FILL,)*6, board=enemy, max_mana=20, mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((actor,other) if pid == 1 else (other,actor),
            active_player=pid, seed=19), registry(mode))

    def play(self, g, cid=CARD, target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid, target_id=target))
        return eid

    def select(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def victim(self, g):
        return g.state.players[3-g.state.active_player].board[0]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry(self.mode)
        other = Game.from_snapshot(saved, r)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for pid in (1,2):
            visible = json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('resolution_frame','beneficiary','zone_epoch','rng_state','StealBonusEffects'):
                self.assertNotIn('"'+field+'"', visible)
        return other

    def assert_reward(self, g, source, n):
        e = g.state.entities[source]
        self.assertEqual((e.attack,e.max_health), (4+n,3+n))

    def test_a00_complete_raw_primary_faces_metadata_and_central_registration(self):
        d = load_batch(); row, = d['cards']; raw = row['record']; card = build_registry().card(CARD)
        self.assertEqual(canonical_digest(raw), row['record_sha256'])
        self.assertEqual(card.metadata, metadata_from_record(raw))
        self.assertEqual((card.cost,card.attack,card.health,card.battlecry), (3,4,3,BODY))
        self.assertEqual(len(d['official_observations']), 2)
        self.assertEqual(tuple(x.value for x in BONUS_EFFECTS), ('taunt','divine_shield','elusive','lifesteal','poisonous','reborn','rush','windfury'))

    def test_a01_real_paid_battlecry_steals_all_eight_and_rewards_without_rng(self):
        g = self.game(); victim = self.victim(g); rng = g.snapshot()['rng_state']
        source = self.play(g, target=victim)
        self.assertEqual(g.state.players[1].mana, 17); self.assert_reward(g, source, 8)
        self.assertEqual(g.state.entities[victim].keywords, set())
        self.assertEqual(g.state.entities[source].keywords, set(BONUS_EFFECTS))
        self.assertEqual(g.snapshot()['rng_state'], rng)
        event, = (e for e in g.events if e.kind == 'bonus_effects_stolen')
        self.assertEqual(dict(event.data)['count'], 8)
        self.assertEqual(dict(event.data)['keywords'], [k.value for k in BONUS_EFFECTS])
        self.assertTrue(g.state.battlecry_history[-1].completed)
        self.portable(g)

    def test_a02_consumed_divine_shield_is_not_stolen_or_counted(self):
        g = self.game(); victim = self.victim(g); self.play(g, HIT)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[victim].keywords)
        source = self.play(g, target=victim); self.assert_reward(g, source, 7)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[source].keywords)

    def test_a03_duplicate_attachments_and_existing_recipient_flag_count_once(self):
        g = self.game(mode='duplicate'); victim = self.victim(g); source = self.play(g, target=victim)
        self.assert_reward(g, source, 8)
        flags = [a for a in g.state.entities[victim].abilities if a.kind == 'keyword' and a.keyword == Keyword.TAUNT]
        self.assertEqual(len(flags), 2); self.assertTrue(all(a.consumed for a in flags))
        self.assertEqual(sum(a.kind == 'keyword' and a.keyword == Keyword.TAUNT and not a.consumed
                             for a in g.state.entities[source].abilities), 2)

    def test_a04_nonbonus_abilities_preserved_and_existing_rush_not_roll_filtered(self):
        g = self.game(enemy=(ODD,)); victim = self.victim(g); source = self.play(g, target=victim)
        self.assert_reward(g, source, 0); e = g.state.entities[victim]
        self.assertEqual(e.keywords, {Keyword.CHARGE})
        self.assertTrue(any(a.kind == 'deathrattle' and not a.consumed for a in e.abilities))
        self.assertTrue(any(a.kind == 'spell_damage' and a.spell_damage == 3 for a in e.abilities))
        g = self.game(); victim = self.victim(g)
        self.assertNotIn(Keyword.RUSH, bonus_candidates(g.state, g.state.entities[victim]))
        source = self.play(g, target=victim); self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)

    def test_a05_enemy_minion_domain_elusive_and_no_available_target(self):
        g = self.game(enemy=(HIDDEN,DORMANT)); source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD)
        for target in (*g.state.players[2].board, g.state.players[2].hero_id):
            before = g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target_id=target))
            self.assertEqual(g.snapshot(), before)
        self.play(g); self.assert_reward(g, source, 0)
        g = self.game(enemy=()); source = self.play(g); self.assert_reward(g, source, 0)
        g = self.game(mode='duplicate'); before = g.snapshot()
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,target_id=g.state.players[1].board[0]))
        self.assertEqual(g.snapshot(), before)

    def test_a06_continuous_aura_is_independent_of_the_copied_effect(self):
        g = self.game(enemy=(FILL,AURA)); victim = self.victim(g)
        self.assertIn(Keyword.TAUNT, g.state.entities[victim].keywords)
        source = self.play(g, target=victim); self.assert_reward(g, source, 1)
        self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)
        self.assertIn(Keyword.TAUNT, g.state.entities[victim].keywords)
        self.assertTrue(any(a.kind == 'keyword_aura' for a in g.state.entities[g.state.players[2].board[1]].abilities))

    def test_a07_source_silence_removes_rewards_without_restoring_victim(self):
        g = self.game(); victim = self.victim(g); source = self.play(g, target=victim)
        self.play(g, SILENCE, source); self.assert_reward(g, source, 0)
        self.assertFalse(g.state.entities[source].keywords)
        self.assertFalse(g.state.entities[victim].keywords)

    def test_a08_current_and_base_copies_keep_independent_source_and_victim_material(self):
        for target_source in (True,False):
            with self.subTest(source=target_source):
                g = self.game(); victim = self.victim(g); source = self.play(g, target=victim)
                target = source if target_source else victim
                self.play(g, COPY, target)
                current = g.state.entities[g.state.players[1].board[-1]]
                self.assertEqual(current.keywords, set(BONUS_EFFECTS) if target_source else set())
                if target_source:self.assertEqual((current.attack,current.max_health), (12,11))
                self.play(g, BASE, target)
                base = g.state.entities[g.state.players[1].board[-1]]
                self.assertEqual(base.keywords, set() if target_source else set(BONUS_EFFECTS))
                if target_source:self.assertEqual((base.attack,base.max_health), (4,3))

    def test_b00_theft_wait_restores_and_keeps_selection_after_original_target_leaves(self):
        g = self.game(mode='wait'); victim = self.victim(g); source = self.play(g, target=victim)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.entities[victim].keywords)
        self.assert_reward(g, source, 0); restored = self.portable(g)
        self.select(g, 'bounce_target'); self.select(restored, 'bounce_target')
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_reward(g, source, 8)
        self.assertEqual(g.state.entities[victim].zone, Zone.HAND)
        self.portable(g)

    def test_b01_mid_grant_source_leave_does_not_rebind_or_reward_hand_entity(self):
        g = self.game(mode='grant'); victim = self.victim(g); source = self.play(g, target=victim)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.entities[source].keywords, {Keyword.TAUNT})
        self.portable(g); self.select(g, 'bounce_source')
        self.assertEqual(g.state.entities[source].zone, Zone.HAND)
        self.assert_reward(g, source, 0); self.assertFalse(g.state.entities[source].keywords)
        self.assertFalse(g.state.entities[victim].keywords); self.portable(g)

    def test_b02_entry_wait_reads_current_flags_after_silence(self):
        g = self.game(mode='entry'); victim = self.victim(g); source = self.play(g, target=victim)
        self.portable(g); self.select(g, 'silence_target')
        self.assert_reward(g, source, 0); self.assertFalse(g.state.entities[source].keywords)
        self.assertFalse(any(e.kind == 'bonus_effects_stolen' for e in g.events)); self.portable(g)

    def test_b03_source_destroyed_before_accepted_battlecry_does_not_cancel_theft(self):
        g = self.game(mode='entry'); victim = self.victim(g); source = self.play(g, target=victim)
        self.select(g, 'kill_source')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(g.state.entities[victim].keywords)
        self.assertTrue(any(e.kind == 'bonus_effects_stolen' for e in g.events)); self.portable(g)

    def test_b04_reaction_failure_rolls_back_payment_installation_theft_and_rng(self):
        g = self.game(mode='fail'); victim = self.victim(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.play(g, target=victim)
        self.assertEqual(g.snapshot(), before)

    def test_b05_failed_choice_preserves_original_wait_and_successful_continuation(self):
        g = self.game(mode='wait'); victim = self.victim(g); source = self.play(g, target=victim)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.select(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.select(g); self.assert_reward(g, source, 8)

    def test_c00_typed_effect_codec_and_future_or_rebound_references_rejected(self):
        g = self.game(); victim = self.victim(g); source = self.play(g, target=victim)
        vr, sr = (MinionReference.capture(g.state.entities[eid]) for eid in (victim,source))
        effect = StealBonusEffects(vr,sr,source); codec = FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(effect)))), effect)
        with self.assertRaises(ValueError):StealBonusEffects(vr,sr,True)
        with self.assertRaises(ValueError):StealBonusEffects(vr,vr,source)
        with self.assertRaises(ValueError):replace(effect,victim=replace(vr,zone_epoch=vr.zone_epoch+1)).validate_in_state(g.state)
        with self.assertRaises(ValueError):replace(effect,beneficiary=replace(sr,entered_order=g.state.next_order)).validate_in_state(g.state)

    def test_c01_other_seat_and_old_schema_rejection(self):
        g = self.game(pid=2); victim = self.victim(g); source = self.play(g, target=victim)
        self.assertEqual(g.state.players[2].mana, 17); self.assert_reward(g, source, 8); self.portable(g)
        snap = deepcopy(g.snapshot()); snap['schema_version'] = 444
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())


if __name__ == '__main__':
    unittest.main()
