"""Captain Crowley's real battlecry and removable additions to native cannon shots."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.cannoneer_shot_quantity_card import CARD, CANNON, load_batch, register_cannoneer_shot_quantity_card
from hs_sim.cards.native_followup_cards import register_cannoneer_behaviors
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup, Registry,
    Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EndTurnSpec, ProducerQuantitySpec
from hs_sim.engine.native_producer_quantities import CANNONEER_SHOT, count
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash

P, CMD = 'k213.', 'k213.cmd_'
HERO, OTHER, WATCH, SPELL = (P+x for x in ('hero', 'other', 'watch', 'spell'))


@lru_cache(None)
def real_cannon():
    from hs_sim.cards import build_registry
    return build_registry().card(CANNON)


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); r.register_card(real_cannon()); register_cannoneer_behaviors(r)
    register_cannoneer_shot_quantity_card(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'armor', lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate shot rollback')))
    r.register_card(CardDefinition(OTHER, OTHER, CardType.MINION, health=20,
        triggers=(TriggerSpec('turn_ended', P+'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, on_play=P+'empty'))
    commands = {
        'silence': lambda c: (Silence(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'sleep': lambda c: (MakeDormant(c.target_id, 2, c.source_id),),
        'wake': lambda c: tuple(AwakenMinion(i, c.source_id) for p in c.state.players.values()
            for i in p.board if c.state.entities[i].dormancy is not None),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'control': lambda c: (ChangeControl(c.target_id, c.player_id),),
        'transform': lambda c: (Transform(c.target_id, OTHER),),
        'summon': lambda c: (Summon(c.player_id, CARD, c.source_id),),
        'cannon': lambda c: (Summon(c.player_id, CANNON, c.source_id),),
    }
    from hs_sim.engine import TargetSpec
    for name, body in commands.items():
        r.register_behavior(CMD+name, body)
        r.register_card(CardDefinition(CMD+name, name, CardType.SPELL, on_play=CMD+name,
            targeting=None if name in ('wake', 'summon', 'cannon') else TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != CANNON or source.controller != c.player_id: return ()
        providers = [i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD]
        if mode == 'kill' and providers: return (Destroy(providers[0], c.source_id),)
        if mode == 'add' and len(providers) == 1: return (Summon(c.player_id, CARD, c.source_id),)
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode == 'wait':
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=(TriggerSpec('damage_dealt', P+'watch'),)))
    r.validate(); return r


class CannoneerShotQuantityTests(unittest.TestCase):
    def game(self, hand=(), board=(CARD, CANNON), enemy=(), enemy_hand=(), owner=1, mode=None):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=(SPELL,)*4, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(SPELL,)*4, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=213), registry(mode))
    def entities(self, g, cid, p=None):
        p = self.owner if p is None else p
        return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id == cid]
    def hero(self, g, p=None): return g.state.entities[g.state.players[3-self.owner if p is None else p].hero_id]
    def play(self, g, cid=CARD, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target)); return eid
    def end(self, g): g.apply(EndTurn(g.state.active_player))
    def shots(self, g):
        return [e for e in g.events if e.kind == 'random_choice' and
            e.source_id in g.state.entities and g.state.entities[e.source_id].card_id == CANNON]
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def finish(self, g):
        while g.state.pending_choice is not None: self.choose(g)
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return restored
    def rehash(self, data):
        data['events_hash'] = canonical_hash(data['events'])
        data['state_hash'] = canonical_hash({k: v for k, v in data.items()
            if k not in ('schema_version', 'state_hash', 'events', 'events_hash')})
        return data
    def test_complete_root_existing_cannon_evidence_and_immutable_quantity_profile(self):
        from hs_sim.cards import build_registry
        r = build_registry(); data = load_batch(); c = r.card(CARD)
        self.assertEqual((c.name, c.cost, c.attack, c.health), ('克罗雷船长', 5, 4, 5))
        self.assertEqual(len(data['official_observations']), 2)
        self.assertNotIn('CAP_106e', r.cards)
        profile = r.native_producer_quantity_profiles[CARD]
        self.assertEqual((profile.receiver_card_id, profile.unit), (CANNON, ProducerQuantitySpec(CANNONEER_SHOT)))
        with self.assertRaises(TypeError): r.native_producer_quantity_profiles[CARD] = profile
        with self.assertRaises(FrozenInstanceError): profile.receiver_card_id = OTHER
    def test_real_battlecry_pays_five_and_summons_two_existing_one_one_cannons_without_immediate_fire(self):
        g = self.game((CARD,), board=()); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 15)
        self.assertEqual([(e.attack, e.max_health) for e in self.entities(g, CANNON)], [(1, 1), (1, 1)])
        self.assertFalse(self.shots(g)); self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertTrue(all(x.request.cause.source.entity_id == source for x in g.state.card_summon_history))
        self.end(g); self.assertEqual(len(self.shots(g)), 4); self.assertEqual(self.hero(g).health, 76); self.portable(g)
    def test_no_source_one_source_and_two_sources_add_shots_to_one_original_body(self):
        for number in (0, 1, 2):
            g = self.game(board=(CARD,)*number+(CANNON,)); self.end(g)
            self.assertEqual((len(self.shots(g)), self.hero(g).health), (1+number, 79-number))
            self.assertEqual(len(g.state.end_turn_history), 1)
    def test_capacity_uses_shared_entry_without_extra_fire_or_fake_tokens(self):
        for count, expected in ((5, 1), (6, 0)):
            g = self.game((CARD,), board=(OTHER,)*count); self.play(g)
            self.assertEqual(len(self.entities(g, CANNON)), expected)
            self.assertEqual(len(g.state.card_summon_history), 2); self.end(g)
            self.assertEqual(len(self.shots(g)), expected*2)
    def test_only_cannons_gain_shots_other_ends_and_enemy_cannons_do_not(self):
        g = self.game(board=(CARD, CANNON, OTHER), enemy=(CANNON,)); self.end(g)
        self.assertEqual(len(self.shots(g)), 2)
        self.assertEqual(self.hero(g, self.owner).armor, 1)
        self.assertEqual({e.source_id for e in self.shots(g)}, {self.entities(g, CANNON)[0].id})
    def test_silence_death_bounce_dormancy_and_transform_remove_future_quantity(self):
        for operation in ('silence', 'kill', 'bounce', 'sleep', 'transform'):
            g = self.game((CMD+operation,)); source = self.entities(g, CARD)[0].id
            self.play(g, CMD+operation, source); self.end(g)
            self.assertEqual(len(self.shots(g)), 1)
    def test_awaken_and_current_copy_keep_independent_removable_sources(self):
        g = self.game((CMD+'sleep', CMD+'wake')); source = self.entities(g, CARD)[0].id
        self.play(g, CMD+'sleep', source); self.play(g, CMD+'wake'); self.end(g)
        self.assertEqual(len(self.shots(g)), 2)
        g = self.game((CMD+'copy', CMD+'kill')); source = self.entities(g, CARD)[0].id
        self.play(g, CMD+'copy', source); self.play(g, CMD+'kill', source); self.end(g)
        self.assertEqual(len(self.shots(g)), 2); self.portable(g)
    def test_control_reassigns_only_future_receiver_owner_without_leaving_old_aura(self):
        g = self.game(board=(CARD, CANNON), enemy_hand=(CMD+'control', CMD+'cannon'))
        source = self.entities(g, CARD)[0].id; self.end(g)
        self.play(g, CMD+'control', source); self.play(g, CMD+'cannon')
        self.assertEqual(count(g.state, g.registry, 1, CANNON, CANNONEER_SHOT), 1)
        self.assertEqual(count(g.state, g.registry, 2, CANNON, CANNONEER_SHOT), 2)
        self.end(g)
        enemy_cannon = self.entities(g, CANNON, 2)[0].id
        self.assertEqual(sum(e.source_id == enemy_cannon for e in self.shots(g)), 2)
        self.assertEqual(len(self.shots(g)), 4); self.portable(g)
    def test_first_body_keeps_accepted_shots_after_provider_death_later_body_requotes(self):
        g = self.game(board=(CARD, CANNON, CANNON, WATCH), mode='kill'); cannons = self.entities(g, CANNON)
        self.end(g); self.assertEqual([sum(e.source_id == c.id for e in self.shots(g)) for c in cannons], [2, 1])
        self.assertFalse(self.entities(g, CARD)); self.portable(g)
    def test_provider_added_mid_body_affects_only_later_body(self):
        g = self.game(board=(CARD, CANNON, CANNON, WATCH), mode='add'); cannons = self.entities(g, CANNON)
        self.end(g); self.assertEqual([sum(e.source_id == c.id for e in self.shots(g)) for c in cannons], [2, 3])
        self.portable(g)
    def test_wait_preserves_accepted_tail_rng_restore_clone_replay_and_failed_choice(self):
        g = self.game(board=(CARD, CANNON, WATCH), mode='wait'); self.end(g)
        self.assertEqual(len(self.shots(g)), 1); self.assertEqual(self.hero(g).health, 79)
        restored = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.finish(g); self.finish(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((len(self.shots(g)), self.hero(g).health), (2, 78)); self.portable(g)
    def test_shot_reaction_exception_rolls_back_whole_end_turn_and_rng(self):
        g = self.game(board=(CARD, CANNON, WATCH), mode='fail'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.end(g)
        self.assertEqual(g.snapshot(), saved)
    def test_direct_summon_has_passive_quantity_but_no_battlecry(self):
        g = self.game((CMD+'summon',), board=(CANNON,)); self.play(g, CMD+'summon')
        self.assertEqual(len(self.entities(g, CANNON)), 1); self.end(g)
        self.assertEqual(len(self.shots(g)), 2)
    def test_real_hand_cannon_shares_extra_shots_without_endturn_even_when_receiver_is_silenced(self):
        from hs_sim.cards import build_registry
        def host():
            r = build_registry()
            r.register_behavior(CMD+'silence', lambda c: (Silence(c.target_id),))
            r.register_card(CardDefinition(CMD+'silence', 'Silence fixture', CardType.SPELL,
                on_play=CMD+'silence', targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
            return r
        self.owner = 1
        for silenced in (False, True):
            g = Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=('CAP_103', CMD+'silence'),
                board=(CARD, CANNON), mana=20, max_mana=20, mana_cap=20), PlayerSetup('HERO_01')), seed=213), host())
            self.play(g, 'CAP_103')
            if silenced: self.play(g, CMD+'silence', self.entities(g, CANNON)[0].id)
            g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
            self.assertEqual(len(self.shots(g)), 2); self.assertFalse(g.state.end_turn_history)
            saved = g.snapshot(); r = host()
            self.assertEqual(Game.from_snapshot(deepcopy(saved), r).snapshot(), saved)
            self.assertEqual(g.clone().snapshot(), saved)
            self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
    def test_both_seats_and_player_views_keep_private_quantity_materials_hidden(self):
        for owner in (1, 2):
            g = self.game(owner=owner); self.end(g); self.assertEqual(len(self.shots(g)), 2)
            for viewer in (1, 2):
                text = json.dumps(g.observe(viewer))
                for key in ('native_producer_quantity', CANNONEER_SHOT, 'next_attachment_id', 'rng_state'):
                    self.assertNotIn(key, text)
            self.portable(g)
    def test_native_marker_and_profile_reject_mixing_foreign_receiver_and_old_schema(self):
        g = self.game(); source = self.entities(g, CARD)[0]
        ability = next(a for a in source.abilities if a.kind == 'native_producer_quantity')
        with self.assertRaises(ValueError): replace(ability, consumed=True)
        profile = g.registry.native_producer_quantity_profiles[CARD]
        with self.assertRaises(ValueError): replace(profile, unit=ProducerQuantitySpec('unknown'))
        with self.assertRaises(ValueError): count(g.state, g.registry, 1, CANNON, 'unknown')
        bad = deepcopy(g.snapshot()); raw = bad['state']['entities'][str(source.id)]
        next(a for a in raw['abilities'] if a['kind'] == 'native_producer_quantity')['native_producer_quantity_card_id'] = OTHER
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(bad), registry())
        bad = deepcopy(g.snapshot()); bad['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())


if __name__ == '__main__': unittest.main()
