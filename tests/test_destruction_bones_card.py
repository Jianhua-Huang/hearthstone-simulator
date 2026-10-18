"""Physical destruction, frozen native stat parameters and their ordinary lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.destruction_bones_card import CARD, BONES, load_batch, register_destruction_bones_card
from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.destruction_spell_values import public_bonus
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, Silence, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.native_spell_values import bound_value
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard

P = 'k210.'
HERO, VICTIM, ZERO, REBORN, WATCH, FILL = (P+x for x in ('hero', 'victim', 'zero', 'reborn', 'watch', 'fill'))


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_destruction_bones_card(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Bones rollback')))
    def wait(c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    def death(c):
        if mode == 'death': return wait(c)
        if mode == 'fill': return (AddToHand(c.player_id, FILL, c.source_id),)
        if mode == 'kill_source':
            return tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id == CARD)
        return ()
    r.register_behavior(P+'death', death)
    for cid, attack, keywords in ((VICTIM, 5, ()), (ZERO, 0, ()), (REBORN, 5, (Keyword.REBORN,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=8,
            deathrattle=P+'death', keywords=keywords))
    def watch(c):
        e = c.state.entities.get(c.event.target_id)
        if e is None or e.card_id != BONES: return ()
        if mode == 'inspect':
            return (GainArmor(c.player_id, 3 if public_bonus(e) == {'attack': 5, 'health': 8} else 1),)
        if mode == 'created' and c.event.kind == 'card_created': return wait(c)
        if mode == 'added' and c.event.kind == 'card_added_to_hand': return wait(c)
        if mode == 'fail_created': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=(TriggerSpec('card_created', P+'watch'), TriggerSpec('card_added_to_hand', P+'watch'))))
    def whole(c):
        excluded = tuple(p.id for p in c.state.play_history if p.id < c.play.id and p.card_id != BONES)
        return (ReplayWholeCards(c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, c.play.id, exclude_play_ids=excluded)),)
    scripts = {
        'hurt': lambda c: (Damage(c.target_id, 3, c.source_id),),
        'grow': lambda c: (Buff(c.target_id, 2, 4, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'copy': lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, source_id=c.source_id),),
        'base': lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, mode='base', source_id=c.source_id),),
        'give': lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 3-c.player_id, Zone.HAND, source_id=c.source_id),),
        'recast': lambda c: (RecastSpell(c.player_id, next(x.id for x in c.state.cast_history if x.card_id == BONES), c.source_id),),
        'whole': whole,
        'summon': lambda c: (Summon(c.player_id, CARD, c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        target = (TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly')
            if name in ('copy', 'base', 'give') else TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if name in ('hurt', 'grow', 'silence', 'kill') else None)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, targeting=target))
    r.register_card(CardDefinition(FILL, FILL, CardType.SPELL, on_play=P+'empty'))
    r.validate(); return r


class DestructionBonesTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(VICTIM,), enemy=(VICTIM,), actor=1, mode=None):
        self.mode = mode
        own = PlayerSetup(HERO, hand=hand, board=board, mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup(HERO, board=enemy, mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=210), registry(mode))
    def entities(self, g, cid, p=None, zone='hand'):
        p = g.state.active_player if p is None else p
        return [g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid]
    def victim(self, g, p=None, cid=VICTIM): return self.entities(g, cid, p, 'board')[0].id
    def play(self, g, cid=CARD, target=None):
        p = g.state.active_player; eid = self.entities(g, cid)[0].id
        g.apply(PlayCard(p, eid, target)); return eid
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return restored
    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'state_hash', 'events', 'events_hash')})
        return saved

    def test_complete_sources_and_central_registration(self):
        from hs_sim.cards import build_registry
        r = build_registry(); raw = load_batch()
        self.assertEqual(len(raw['official_observations']), 4)
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (3, 3, 3))
        self.assertEqual((r.card(BONES).cost, r.card(BONES).kind, r.card(BONES).metadata.collectible), (2, CardType.SPELL, False))
        self.assertEqual(r.spell_value_profiles[BONES].value_kind, 'stat_grant')
    def test_actual_destroy_creates_bound_bones_then_real_cast_buffs_target(self):
        g = self.game(); victim = self.victim(g); self.play(g, target=victim)
        bones = self.entities(g, BONES)[0]
        self.assertEqual(g.state.players[1].mana, 77)
        self.assertEqual(g.state.entities[victim].zone, Zone.GRAVEYARD)
        self.assertEqual(public_bonus(bones), {'attack': 5, 'health': 8})
        self.assertEqual(bound_value(bones).cause, g.state.death_history[0].cause)
        target = self.victim(g, 2); self.play(g, BONES, target)
        e = g.state.entities[target]; self.assertEqual((e.attack, e.max_health), (10, 16))
        self.assertEqual(g.state.players[1].mana, 75)
        self.assertEqual(g.state.cast_history[-1].native_spell_value.spell_stat_value, bound_value(bones))
        self.portable(g)
    def test_original_current_attack_and_remaining_health_include_buffs_and_damage(self):
        g = self.game((P+'grow', P+'hurt', CARD)); v = self.victim(g)
        self.play(g, P+'grow', v); self.play(g, P+'hurt', v); self.play(g, target=v)
        self.assertEqual(public_bonus(self.entities(g, BONES)[0]), {'attack': 7, 'health': 9})
        self.portable(g)
    def test_zero_attack_is_bound_not_missing_or_default(self):
        g = self.game(board=(ZERO,)); self.play(g, target=self.victim(g, cid=ZERO))
        self.assertEqual(public_bonus(self.entities(g, BONES)[0]), {'attack': 0, 'health': 8})
        target = self.victim(g, 2); self.play(g, BONES, target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (5, 16))
    def test_target_must_be_other_live_friendly_minion_and_omission_is_illegal_when_available(self):
        g = self.game(); before = g.snapshot()
        for target in (None, self.victim(g, 2), g.state.players[1].hero_id):
            with self.assertRaises(IllegalAction): self.play(g, target=target)
            self.assertEqual(g.snapshot(), before)
    def test_no_victim_still_plays_and_normal_summon_has_no_battlecry(self):
        g = self.game(board=()); self.play(g)
        self.assertFalse(self.entities(g, BONES)); self.assertEqual(g.state.players[1].mana, 77)
        g = self.game((P+'summon',)); self.play(g, P+'summon')
        self.assertFalse(self.entities(g, BONES)); self.assertEqual(len(g.state.death_history), 0)
    def test_reborn_does_not_replace_original_stats_or_duplicate_reward(self):
        g = self.game(board=(REBORN,)); v = self.victim(g, cid=REBORN); self.play(g, target=v)
        self.assertEqual(len(self.entities(g, BONES)), 1)
        self.assertEqual(public_bonus(self.entities(g, BONES)[0]), {'attack': 5, 'health': 8})
        self.assertEqual(self.entities(g, REBORN, zone='board')[0].health, 1)
        self.portable(g)
    def test_victim_deathrattle_can_destroy_source_without_losing_accepted_reward(self):
        g = self.game(mode='kill_source'); source = self.play(g, target=self.victim(g))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(public_bonus(self.entities(g, BONES)[0]), {'attack': 5, 'health': 8})
        self.portable(g)
    def test_first_creation_and_acquisition_notifications_have_complete_stats(self):
        g = self.game(board=(VICTIM, WATCH), mode='inspect'); self.play(g, target=self.victim(g))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
    def test_full_hand_uses_normal_burn_and_does_not_create_an_unbound_spell(self):
        g = self.game((CARD,)+(FILL,)*9, mode='fill'); self.play(g, target=self.victim(g))
        self.assertFalse(self.entities(g, BONES))
        bones = [e for e in g.state.entities.values() if e.card_id == BONES]
        self.assertEqual(len(bones), 1); self.assertEqual(bones[0].zone, Zone.GRAVEYARD)
        self.assertEqual(public_bonus(bones[0]), {'attack': 5, 'health': 8}); self.portable(g)
    def test_current_copy_retains_values_with_independent_attachment_identity(self):
        g = self.game((CARD, P+'copy')); self.play(g, target=self.victim(g))
        original = self.entities(g, BONES)[0]; self.play(g, P+'copy', original.id)
        bones = self.entities(g, BONES); self.assertEqual(len(bones), 2)
        self.assertEqual(bound_value(bones[0]), bound_value(bones[1]))
        self.assertNotEqual(bones[0].abilities[0].id, bones[1].abilities[0].id)
        for _ in range(2): self.play(g, BONES, self.victim(g, 2))
        self.assertEqual(g.state.entities[self.victim(g, 2)].max_health, 24); self.portable(g)
    def test_base_copy_and_direct_unbound_bones_explicitly_reject_cast(self):
        g = self.game((BONES,)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, BONES, self.victim(g, 2))
        self.assertEqual(g.snapshot(), before)
        self.assertIsNone(g.for_player(1).legal_actions()['actions'])
        g = self.game((CARD, P+'base')); self.play(g, target=self.victim(g))
        self.play(g, P+'base', self.entities(g, BONES)[0].id)
        copies = self.entities(g, BONES); self.assertIsNone(bound_value(copies[1]))
    def test_spell_and_whole_card_replays_inherit_original_parameters(self):
        for command in ('recast', 'whole'):
            g = self.game((CARD, P+command)); self.play(g, target=self.victim(g))
            self.play(g, BONES, self.victim(g, 2)); self.play(g, P+command)
            casts = [c for c in g.state.cast_history if c.card_id == BONES]
            self.assertEqual(len(casts), 2)
            self.assertEqual(casts[0].native_spell_value.spell_stat_value, casts[1].native_spell_value.spell_stat_value)
            self.portable(g)
    def test_death_and_both_delivery_waits_restore_clone_replay_and_resume_once(self):
        for mode in ('death', 'created', 'added'):
            g = self.game(board=(VICTIM, WATCH), mode=mode); self.play(g, target=self.victim(g))
            self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
            before = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), before)
            self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(len(self.entities(g, BONES)), 1)
            self.portable(g)
    def test_failed_creation_reaction_rolls_back_destruction_payment_and_binding(self):
        g = self.game(board=(VICTIM, WATCH), mode='fail_created'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, target=self.victim(g))
        self.assertEqual(g.snapshot(), before)
    def test_both_seats_and_player_projection_show_only_visible_stat_pair(self):
        for actor in (1, 2):
            g = self.game(actor=actor); self.play(g, target=self.victim(g))
            own, other = g.observe(actor), g.observe(3-actor)
            shown = next(x for x in own['players'][actor-1]['hand'] if x.get('card_id') == BONES)
            self.assertEqual(shown['stat_bonus'], {'attack': 5, 'health': 8})
            self.assertNotIn('stat_bonus', json.dumps(other['players'][actor-1]['hand']))
            for view in (own, other):
                text = json.dumps(view)
                for key in ('spell_stat_value', 'native_spell_value', 'death_history', 'target_zone_epoch'):
                    self.assertNotIn(key, text)
            self.portable(g)
    def test_typed_values_profiles_mixing_old_schema_and_missing_cast_claim_reject(self):
        g = self.game(); self.play(g, target=self.victim(g)); value = bound_value(self.entities(g, BONES)[0])
        for changes in ({'attack': -1}, {'attack': True}, {'health': 0}, {'health': False}):
            with self.assertRaises(ValueError): replace(value, **changes)
        ability = self.entities(g, BONES)[0].abilities[0]
        with self.assertRaises(ValueError): replace(ability, spell_damage=2)
        self.play(g, BONES, self.victim(g, 2)); saved = g.snapshot()
        bad = deepcopy(saved); bad['state']['cast_history'][-1]['native_spell_value'] = None
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(bad), registry())
        bad = deepcopy(saved); bad['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())


if __name__ == '__main__': unittest.main()
