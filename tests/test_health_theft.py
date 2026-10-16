"""Character theft shares ordinary stat/hero growth and portable interpreter work."""
from random import Random
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
                           PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_theft import RandomStealHealthToHero, StealHealthToHero
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference


def registry(mode=None):
    r = build_registry()
    for cid, attack, health, keywords, extra in (
        ('big', 2, 8, (), {}), ('new', 1, 8, (), {}),
        ('shield', 1, 2, (Keyword.DIVINE_SHIELD,), {}),
        ('immune', 1, 8, (Keyword.IMMUNE,), {}),
        ('bonus', 1, 5, (), dict(spell_damage=3)),
        ('sleep', 1, 8, (), dict(dormant_turns=3)),
    ):
        r.register_card(CardDefinition('k15.'+cid, cid, CardType.MINION, attack=attack, health=health,
                                      keywords=keywords, **extra))
    def reference(c, eid):
        e = c.state.entities[eid]
        return MinionReference.capture(e) if e.kind == CardType.MINION else eid
    def pool(c):
        return tuple(reference(c, eid) for eid in c.state.players[2].board
                     if c.state.entities[eid].card_id in ('k15.big', 'k15.new'))
    scripts = {
        'noop': lambda c: (),
        'hit': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'wound': lambda c: (Damage(c.state.players[1].hero_id, 7, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k15'),),
        'theft': lambda c: (StealHealthToHero(c.player_id, reference(c, c.target_id), 3, c.source_id),),
        'auto_theft': lambda c: (StealHealthToHero(c.player_id,
            reference(c, c.state.players[2].board[0]), 3, c.source_id),),
        'zero': lambda c: (RandomStealHealthToHero(c.player_id, pool(c), 0, c.source_id),),
        'bad_source': lambda c: (RandomStealHealthToHero(c.player_id, (), 1, 999999),),
        'random': lambda c: (RandomStealHealthToHero(c.player_id, pool(c), 3, c.source_id),),
        'wound_new': lambda c: tuple(Damage(eid, 2, c.source_id) for eid in c.state.players[1].board
                                    if c.state.entities[eid].card_id == 'k15.new'),
    }
    for name, body in scripts.items():
        r.register_behavior('k15.'+name, body)
        r.register_card(CardDefinition('k15.'+name, name, CardType.SPELL, on_play='k15.'+name,
            requires_target=name in ('hit', 'silence', 'kill', 'theft')))
    if mode:
        def watch(c):
            card = c.state.entities[c.event.source_id].card_id
            if mode == 'atomic':
                if card != 'k15.theft': return ()
                assert c.state.entities[c.state.players[1].hero_id].health == 33
                assert c.state.entities[c.event.target_id].max_health == 5
                options = (ChoiceOption('ok', 'Continue', (GainArmor(1, 1),)),)
            elif mode == 'random':
                if card != 'k15.random': return ()
                options = (ChoiceOption('ok', 'Move selected original',
                    (ReturnToHand(c.event.target_id), Summon(2, 'k15.big'))),)
            else:
                if card != 'EDR_476' or c.state.entities[c.event.target_id].kind != CardType.MINION:
                    return ()
                options = (ChoiceOption('ok', 'Create wounded friendly target',
                    (Summon(1, 'k15.new'), InvokeBehavior('k15.wound_new', c.source_id, 1))),)
            return (RequestChoice(1, (*options, ChoiceOption('bad', 'Rollback',
                (InvokeBehavior('k15.fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior('k15.watch', watch)
        event = 'stats_changed' if mode == 'atomic' else 'random_choice' if mode == 'random' else 'damage_dealt'
        r.register_card(CardDefinition('k15.watch', 'Observer', CardType.MINION, health=8,
                                      triggers=(TriggerSpec(event, 'k15.watch'),)))
    return r


class HealthTheftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry = registry()

    def game(self, hand=('k15.theft',), *, board=(), enemy=('k15.big',), mode=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero', hand=hand, board=board, deck=('CORE_CS2_182',)*4,
                        mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('test.hero', board=enemy, deck=('CORE_CS2_182',)*4, armor=9)), seed=239),
            registry(mode) if mode else self.registry)

    def play(self, g, cid, target=None):
        eid = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid

    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]

    def portable(self, g, mode=None):
        saved = g.snapshot(); other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved)
        return other

    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def test_minion_and_hero_deficits_are_preserved_without_damage_or_healing(self):
        g = self.game(('k15.wound', 'k15.hit', 'k15.theft')); donor = g.state.players[2].board[0]
        self.play(g, 'k15.wound'); self.play(g, 'k15.hit', donor); before = len(g.events)
        self.play(g, 'k15.theft', donor)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health), (26, 33))
        self.assertEqual((g.state.entities[donor].health, g.state.entities[donor].max_health), (4, 5))
        self.assertFalse(any(e.kind in ('damage_dealt', 'healed', 'health_lost') for e in g.events[before:]))
        self.portable(g)

    def test_minion_silence_restores_its_debuff_but_hero_keeps_permanent_gain(self):
        g = self.game(('k15.theft', 'k15.silence')); donor = g.state.players[2].board[0]
        self.play(g, 'k15.theft', donor); self.play(g, 'k15.silence', donor)
        self.assertEqual((g.state.entities[donor].health, g.state.entities[donor].max_health), (8, 8))
        self.assertEqual((self.hero(g).health, self.hero(g).max_health), (33, 33))

    def test_shield_and_immunity_do_not_intercept_and_theft_caps_at_donor_maximum(self):
        for cid, expected in (('k15.shield', 2), ('k15.immune', 3)):
            g = self.game(('k15.auto_theft',), enemy=(cid,)); donor = g.state.players[2].board[0]
            self.play(g, 'k15.auto_theft')
            self.assertEqual(self.hero(g).health, 30+expected)
            self.assertFalse(any(e.kind in ('shield_lost', 'damage_dealt', 'healed') for e in g.events))
            if cid.endswith('shield'): self.assertFalse(g.state.players[2].board)
            else: self.assertEqual(g.state.entities[donor].health, 5)

    def test_hero_donor_reuses_original_permanent_transfer_and_ignores_armor(self):
        g = self.game(); self.play(g, 'k15.theft', self.hero(g, 2).id)
        self.assertEqual((self.hero(g, 2).health, self.hero(g, 2).max_health, self.hero(g, 2).armor), (27, 27, 9))
        self.assertEqual(self.hero(g).health, 33)
        self.assertEqual(sum(e.kind == 'hero_health_stolen' for e in g.events), 1)

    def test_atomic_first_reaction_sees_both_commits_and_waiting_restores(self):
        g = self.game(board=('k15.watch',), mode='atomic'); donor = g.state.players[2].board[0]
        self.play(g, 'k15.theft', donor); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'atomic'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g, 'atomic')

    def test_random_wait_keeps_original_reference_without_redrawing_after_return(self):
        g = self.game(('k15.random',), board=('k15.watch',), enemy=('k15.big', 'k15.new'), mode='random')
        rng = Random(); rng.setstate(g._rng.getstate()); ids = g.state.players[2].board
        selected = rng.choice(ids); self.play(g, 'k15.random')
        self.assertEqual(next(e.target_id for e in g.events if e.kind == 'random_choice'), selected)
        other = self.portable(g, 'random'); before = g._rng.getstate()
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.hero(g).health, 30)
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1)
        self.portable(g, 'random')

    def test_zero_and_empty_pools_do_not_consume_rng_or_create_attachments(self):
        for cid in ('k15.zero', 'k15.random'):
            g = self.game((cid,), enemy=())
            before = g.snapshot(); self.play(g, cid)
            self.assertEqual(g.snapshot()['rng_state'], before['rng_state'])
            self.assertEqual(g.state.next_attachment_id, before['state']['next_attachment_id'])
            self.assertEqual(self.hero(g).health, 30)

    def test_unknown_source_is_rejected_even_for_empty_random_pool(self):
        g = self.game(('k15.bad_source',)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k15.bad_source')
        self.assertEqual(g.snapshot(), saved)

    def test_exact_typed_codec_and_rejects_duplicate_bool_and_untyped_candidates(self):
        g = self.game(); ref = MinionReference.capture(g.state.entities[g.state.players[2].board[0]])
        codec = FrameCodec(g.mechanics, g.registry)
        for request in (StealHealthToHero(1, ref, 3, g.state.players[1].hand[0]),
                        RandomStealHealthToHero(1, (ref, self.hero(g, 2).id), 1, g.state.players[1].hand[0])):
            self.assertEqual(codec.decode(codec.encode(request)), request)
        for args in ((1, (ref, ref), 1, 1), (True, (ref,), 1, 1), (1, [ref], 1, 1), (1, (ref,), True, 1)):
            with self.assertRaises(ValueError): RandomStealHealthToHero(*args)


if __name__ == '__main__': unittest.main()
