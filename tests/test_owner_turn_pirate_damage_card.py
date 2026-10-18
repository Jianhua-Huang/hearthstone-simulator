"""Real Blast Engineer, current Pirate sources and the actual provider owner's turn."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.owner_turn_pirate_damage_card import CARD, RELATION, RULE, load_batch, register_owner_turn_pirate_damage_card
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, GrantKeyword,
    Heal, InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, HealthLayer, HealthOp, TribeChangeSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes

P = 'k212.'
C = P+'cmd_'
HERO, PIRATE, DUAL, ALL, BEAST, UNKNOWN, DEAD, LEECH, WATCH, SPELL = (
    P+x for x in ('hero', 'pirate', 'dual', 'all', 'beast', 'unknown', 'dead', 'leech', 'watch', 'spell'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_owner_turn_pirate_damage_card(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80, metadata=META))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Pirate rollback')))
    def ability(c):
        return (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id, DamageKind.MINION_ABILITY),)
    r.register_behavior(P+'ability', ability)
    for cid, tribes, health, keywords in (
        (PIRATE, ('pirate',), 10, ()), (DUAL, ('beast', 'pirate'), 10, ()),
        (ALL, ('all',), 10, ()), (BEAST, ('beast',), 10, ()), (UNKNOWN, None, 10, ()),
        (DEAD, ('pirate',), 1, ()), (LEECH, ('pirate',), 10, (Keyword.LIFESTEAL,)),
    ):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=health,
            battlecry=P+'ability', deathrattle=P+'ability' if cid == DEAD else None,
            metadata=replace(META, tribes=tribes), keywords=keywords))
    def trigger(c, count=1):
        source = c.state.entities[c.target_id]
        return tuple(Damage(c.state.players[3-source.controller].hero_id, 2, source.id, DamageKind.MINION_ABILITY)
            for _ in range(count))
    scripts = {
        'trigger': lambda c: trigger(c), 'burst': lambda c: trigger(c, 2),
        'silence': lambda c: (Silence(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'sleep': lambda c: (MakeDormant(c.target_id, 1, c.source_id),),
        'wake': lambda c: tuple(AwakenMinion(i, c.source_id) for p in c.state.players.values()
            for i in p.board if c.state.entities[i].dormancy is not None),
        'control': lambda c: (ChangeControl(c.target_id, c.player_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'beast': lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', ('beast',)), c.source_id),),
        'pirate': lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', ('pirate',)), c.source_id),),
        'hurt': lambda c: (Damage(c.target_id, 4, c.source_id, DamageKind.SPELL),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(C+name, name, CardType.SPELL, on_play=P+name,
            targeting=None if name == 'wake' else TargetSpec() if name == 'hurt' else
                TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=META))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, on_play=P+'empty', metadata=META))
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if mode is None or source is None or source.card_id != PIRATE: return ()
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        provider = next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD), None)
        options = [ChoiceOption('ok', 'Continue'), ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))]
        if provider is not None: options.append(ChoiceOption('silence', 'Silence provider', (Silence(provider),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=(TriggerSpec('damage_dealt', P+'watch'),), metadata=META))
    r.validate(); return r


class OwnerTurnPirateDamageTests(unittest.TestCase):
    def game(self, hand=(), board=(CARD, PIRATE), enemy=(), enemy_hand=(), owner=1, active=None, mode=None):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=(SPELL,)*4, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(SPELL,)*4, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner if active is None else active, seed=212), registry(mode))
    def entity(self, g, cid, p=None, zone='board'):
        p = self.owner if p is None else p
        return next(g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)
    def hero(self, g, p=None): return g.state.entities[g.state.players[3-self.owner if p is None else p].hero_id]
    def play(self, g, cid, target=None, p=None):
        p = g.state.active_player if p is None else p
        eid = self.entity(g, cid, p, 'hand').id; g.apply(PlayCard(p, eid, target)); return eid
    def attack(self, g, cid=PIRATE, p=None, target=None):
        p = self.owner if p is None else p
        g.apply(Attack(p, self.entity(g, cid, p).id, self.hero(g, 3-p).id if target is None else target))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return restored
    def test_complete_real_face_and_native_source_rule(self):
        from hs_sim.cards import build_registry
        r = build_registry(); c = r.card(CARD)
        self.assertEqual((c.name, c.cost, c.attack, c.health), ('炸药工程师', 2, 2, 3))
        self.assertEqual(c.metadata.tribes, ('pirate',)); self.assertEqual(c.health_rules, (RULE,))
        self.assertEqual(len(load_batch()['official_observations']), 2)
    def test_real_play_pays_two_and_immediately_enables_damage_without_changing_attack(self):
        g = self.game((CARD,), board=(PIRATE,)); self.play(g, CARD); self.attack(g)
        self.assertEqual(g.state.players[1].mana, 18); self.assertEqual(self.hero(g).health, 77)
        self.assertEqual(self.entity(g, PIRATE).attack, 2); self.portable(g)
    def test_provider_itself_is_a_pirate_and_independent_sources_stack(self):
        for count in (1, 2):
            g = self.game(board=(CARD,)*count); self.attack(g, CARD)
            self.assertEqual(self.hero(g).health, 78-count); self.assertEqual(self.entity(g, CARD).attack, 2)
    def test_current_secondary_and_all_tribes_match_but_ordinary_beast_does_not(self):
        for cid, damage in ((PIRATE, 3), (DUAL, 3), (ALL, 3), (BEAST, 2)):
            g = self.game(board=(CARD, cid)); self.attack(g, cid); self.assertEqual(self.hero(g).health, 80-damage)
    def test_actual_current_tribe_changes_remove_and_add_qualification(self):
        g = self.game((C+'beast', C+'trigger', C+'pirate', C+'trigger'))
        source = self.entity(g, PIRATE).id
        self.play(g, C+'beast', source); self.play(g, C+'trigger', source)
        self.assertEqual(self.hero(g).health, 78)
        self.play(g, C+'pirate', source); self.play(g, C+'trigger', source)
        self.assertEqual(self.hero(g).health, 75); self.portable(g)
    def test_minion_ability_and_original_dead_pirate_match_but_actual_spell_does_not(self):
        g = self.game((PIRATE, C+'hurt', C+'kill'), board=(CARD, DEAD))
        self.play(g, PIRATE); self.assertEqual(self.hero(g).health, 77)
        self.play(g, C+'hurt', self.hero(g).id); self.assertEqual(self.hero(g).health, 73)
        self.play(g, C+'kill', self.entity(g, DEAD).id); self.assertEqual(self.hero(g).health, 70)
        self.portable(g)
    def test_opponent_turn_retaliation_is_not_boosted_then_next_owner_turn_is(self):
        g = self.game(enemy=(PIRATE,), active=2); provider = self.entity(g, CARD)
        ids = tuple(a.id for a in provider.abilities if a.kind == 'health_rule')
        target = self.entity(g, PIRATE).id; attacker = self.entity(g, PIRATE, 2).id
        g.apply(Attack(2, attacker, target)); self.assertEqual(g.state.entities[attacker].health, 8)
        g.apply(EndTurn(2)); self.attack(g); self.assertEqual(self.hero(g).health, 77)
        self.assertEqual(tuple(a.id for a in self.entity(g, CARD).abilities if a.kind == 'health_rule'), ids)
        self.portable(g)
    def test_enemy_pirate_not_boosted_and_provider_control_uses_new_owner_turn(self):
        g = self.game(enemy=(PIRATE,), enemy_hand=(C+'control',), active=2)
        self.play(g, C+'control', self.entity(g, CARD).id, p=2)
        self.attack(g, p=2); self.assertEqual(self.hero(g, 1).health, 77)
        g.apply(EndTurn(2)); self.attack(g); self.assertEqual(self.hero(g).health, 78); self.portable(g)
    def test_silence_death_bounce_and_dormancy_remove_new_packet_bonus(self):
        for operation in ('silence', 'kill', 'bounce', 'sleep'):
            g = self.game((C+operation, C+'trigger'))
            self.play(g, C+operation, self.entity(g, CARD).id)
            self.play(g, C+'trigger', self.entity(g, PIRATE).id)
            self.assertEqual(self.hero(g).health, 78)
    def test_awaken_and_current_copy_restore_only_their_own_live_source(self):
        g = self.game((C+'sleep', C+'wake', C+'trigger'))
        provider = self.entity(g, CARD).id; self.play(g, C+'sleep', provider); self.play(g, C+'wake')
        self.play(g, C+'trigger', self.entity(g, PIRATE).id); self.assertEqual(self.hero(g).health, 77)
        g = self.game((C+'copy', C+'kill', C+'trigger')); provider = self.entity(g, CARD).id
        self.play(g, C+'copy', provider); self.play(g, C+'kill', provider)
        self.play(g, C+'trigger', self.entity(g, PIRATE).id); self.assertEqual(self.hero(g).health, 77); self.portable(g)
    def test_lifesteal_heals_only_actual_boosted_damage_and_shield_prevents_entire_packet(self):
        g = self.game((C+'hurt',), board=(CARD, LEECH)); self.play(g, C+'hurt', self.hero(g, 1).id)
        self.attack(g, LEECH); self.assertEqual((self.hero(g).health, self.hero(g, 1).health), (77, 79))
        g = self.game((C+'shield',), enemy=(PIRATE,)); enemy = self.entity(g, PIRATE, 2).id
        self.play(g, C+'shield', enemy); self.attack(g, target=enemy)
        self.assertEqual(g.state.entities[enemy].health, 10)
    def test_unknown_current_tribe_fails_atomically_without_consuming_attack(self):
        g = self.game(board=(CARD, UNKNOWN)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.attack(g, UNKNOWN)
        self.assertEqual(g.snapshot(), saved)
    def test_damage_wait_restores_and_new_packet_rechecks_silenced_provider(self):
        g = self.game((C+'burst',), board=(CARD, PIRATE, WATCH), mode='wait')
        self.play(g, C+'burst', self.entity(g, PIRATE).id); self.assertEqual(self.hero(g).health, 77)
        restored = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        for game in (g, restored):
            self.choose(game, 'silence'); self.assertEqual(self.hero(game).health, 75); self.choose(game)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)
    def test_damage_reaction_failure_rolls_back_payment_damage_and_source_query(self):
        g = self.game((C+'trigger',), board=(CARD, PIRATE, WATCH), mode='fail'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, C+'trigger', self.entity(g, PIRATE).id)
        self.assertEqual(g.snapshot(), saved)
    def test_both_seats_player_views_and_bound_rule_domain(self):
        for owner in (1, 2):
            g = self.game(owner=owner); self.attack(g); self.assertEqual(self.hero(g).health, 77)
            for viewer in (1, 2):
                text = json.dumps(g.observe(viewer))
                for key in (RELATION, 'health_rule', 'rule_ids', 'rng_state'): self.assertNotIn(key, text)
            self.portable(g)
        for changes in ({'amount': 2}, {'target_relation': 'enemy'}, {'layer': HealthLayer.TARGET},
                {'operation': HealthOp.SCALE}, {'damage_kinds': (DamageKind.COMBAT,)}):
            with self.assertRaises(ValueError): replace(RULE, **changes)
        bad = deepcopy(g.snapshot()); bad['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())


if __name__ == '__main__': unittest.main()
