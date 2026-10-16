"""All five Dream outcomes use one finite draw and ordinary hand delivery."""
from copy import deepcopy
from dataclasses import asdict
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.fixed_dream_source import DRYAD, DREAMS, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.pools import GenerateFromCandidates, GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P = 'k102c.'
YETI = 'CORE_CS2_182'


def registry():
    r = build_registry()
    def draw(c, ids=DREAMS): return GenerateFromCandidates(c.player_id, ids, c.source_id)
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Get a real Dream', (draw(c),)),
            ChoiceOption('fail', 'Fail after draw', (draw(c), InvokeBehavior(P+'fail', c.source_id, c.player_id))),
        ), c.source_id),)
    scripts = {
        'wait': wait,
        'full': lambda c: (AddToHand(c.player_id, YETI, c.source_id), draw(c)),
        'late_fail': lambda c: (draw(c), InvokeBehavior(P+'fail', c.source_id, c.player_id)),
        'unknown': lambda c: (draw(c, (DREAMS[0], 'missing.finite.dream')),),
        'descriptor': lambda c: (draw(c, (DREAMS[0], 'UNG_999t5')),),
        'power': lambda c: (draw(c, (DREAMS[0], 'HERO_08bp')),),
        'bad_source': lambda c: (GenerateFromCandidates(c.player_id, DREAMS, 999999),),
        'reordered': lambda c: (draw(c, tuple(reversed(DREAMS))),),
    }
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate fixed Dream rollback')))
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    def added(c):
        if c.state.entities[c.event.target_id].card_id not in DREAMS: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue after real delivery', ()),), c.source_id),)
    r.register_behavior(P+'added', added)
    r.register_card(CardDefinition(P+'watch', 'Hand delivery witness', CardType.MINION, health=10,
        triggers=(TriggerSpec('card_added_to_hand', P+'added'),)))
    r.register_card(CardDefinition(P+'repeat', 'Repeat fixture', CardType.MINION, health=10,
        battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.validate()
    return r


class FixedDreamSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(DRYAD,), board=(), active=1, context=None, seed=1020):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand if active==1 else (), board=board if active==1 else (),
                deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=hand if active==2 else (), board=board if active==2 else (),
                deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
        ), seed=seed, active_player=active, generation_context=context), self.r)
    def play(self, g, cid=DRYAD):
        p=g.state.active_player; i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p, i, position=len(g.state.players[p].board) if cid==DRYAD else None)); return i
    def cards(self, g, p=None):
        return [g.state.entities[i].card_id for i in g.state.players[p or g.state.active_player].hand]
    def choose(self, g, key='ok'):
        q=g.state.pending_choice; g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def expected_draws(self, g, count=1):
        rng=random.Random(); rng.setstate(g._rng.getstate())
        ids=[DREAMS[rng.randrange(len(DREAMS))]for _ in range(count)]
        return ids,rng.getstate()
    def portable(self, g):
        s=json.loads(json.dumps(g.snapshot())); other=Game.from_snapshot(s,registry())
        self.assertEqual(other.snapshot(),s); self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return other
    def nodes(self, v):
        if isinstance(v,dict):
            if v.get('type','').endswith('.GenerateFromCandidates'): yield v['fields']
            for child in v.values(): yield from self.nodes(child)
        elif isinstance(v,list):
            for child in v: yield from self.nodes(child)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_exact_five_definitions_and_primary_children(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['existing_dependencies']),DREAMS)
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(self.r.card(row['record']['id']))),row['definition_sha256'])
        primary=[x['face']for x in d['official_observations']if x['card_id']==DRYAD]
        self.assertEqual(len(primary),2)
        self.assertTrue(all(sorted(x['childIds'])==[217,301,340,489,808]for x in primary))

    def test_every_exact_outcome_is_reachable_with_one_equal_ticket(self):
        for ticket,cid in enumerate(DREAMS):
            with self.subTest(cid=cid):
                seed=next(s for s in range(1000)if random.Random(s).randrange(5)==ticket)
                g=self.game(seed=seed);expected,after=self.expected_draws(g);self.play(g)
                self.assertEqual(expected,[cid]);self.assertEqual(self.cards(g),[cid])
                self.assertEqual(g._rng.getstate(),after)

    def test_normal_payment_body_and_deterministic_shared_sampling(self):
        g=self.game();expected,after=self.expected_draws(g);source=self.play(g)
        self.assertEqual(self.cards(g),expected);self.assertEqual(g._rng.getstate(),after)
        self.assertEqual(g.state.players[1].mana,37)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,3))
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_original_player_two_receives_own_dream(self):
        g=self.game(active=2);expected,_=self.expected_draws(g);self.play(g)
        self.assertEqual(self.cards(g,2),expected);self.assertEqual(self.cards(g,1),[]);self.portable(g)

    def test_fixed_recipe_does_not_require_a_generation_context(self):
        g=self.game();self.assertIsNone(g._generation_context);self.play(g);self.assertEqual(len(self.cards(g)),1)

    def test_unrelated_format_pool_context_cannot_crop_fixed_recipe(self):
        g=self.game(context=GenerationContext('unrelated-fixed-test','experimental'))
        expected,_=self.expected_draws(g);self.play(g);self.assertEqual(self.cards(g),expected);self.portable(g)

    def test_source_order_does_not_change_canonical_equal_weights(self):
        g=self.game(hand=(P+'reordered',));expected,after=self.expected_draws(g);self.play(g,P+'reordered')
        self.assertEqual(self.cards(g),expected);self.assertEqual(g._rng.getstate(),after)

    def test_full_hand_still_draws_then_uses_ordinary_burn(self):
        g=self.game(hand=(P+'full',)+(YETI,)*9);expected,after=self.expected_draws(g);source=self.play(g,P+'full')
        self.assertEqual(self.cards(g),[YETI]*10);self.assertEqual(g._rng.getstate(),after)
        burnt=[e for e in g.state.entities.values()if e.card_id in DREAMS]
        self.assertEqual(len(burnt),1);self.assertEqual(burnt[0].card_id,expected[0])
        self.assertEqual(burnt[0].zone,Zone.GRAVEYARD)
        self.assertTrue(any(e.kind=='card_burned'and e.target_id==burnt[0].id for e in g.events));self.portable(g)

    def test_repeat_battlecry_gets_two_independent_draws_with_one_payment(self):
        g=self.game(board=(P+'repeat',));expected,after=self.expected_draws(g,2);self.play(g)
        self.assertEqual(self.cards(g),expected);self.assertEqual(g._rng.getstate(),after)
        self.assertEqual(g.state.players[1].mana,37);self.portable(g)

    def test_queued_generation_wait_restores_before_rng_draw(self):
        g=self.game(hand=(P+'wait',));self.play(g,P+'wait');self.assertTrue(list(self.nodes(g.snapshot())))
        expected,after=self.expected_draws(g);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cards(g),expected)
        self.assertEqual(g._rng.getstate(),after)

    def test_actual_delivery_wait_does_not_redraw_after_restore(self):
        g=self.game(board=(P+'watch',));expected,after=self.expected_draws(g);self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.cards(g),expected)
        other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),after)

    def test_after_draw_failure_rolls_back_rng_cards_events_and_payment(self):
        g=self.game(hand=(P+'late_fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'late_fail')
        self.assertEqual(g.snapshot(),before)

    def test_choice_failure_keeps_original_wait_and_random_state(self):
        g=self.game(hand=(P+'wait',));self.play(g,P+'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(self.cards(g)),1)

    def test_unknown_unselected_candidate_fails_before_rng(self):
        g=self.game(hand=(P+'unknown',));before=g.snapshot()
        with patch('random.Random.randrange',return_value=0)as draw:
            with self.assertRaises(ValueError):self.play(g,P+'unknown')
        draw.assert_not_called();self.assertEqual(g.snapshot(),before)

    def test_nonphysical_candidates_and_unknown_source_fail_before_rng(self):
        for cid in (P+'descriptor',P+'power',P+'bad_source'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));before=g.snapshot()
                with self.assertRaises(ValueError):self.play(g,cid)
                self.assertEqual(g.snapshot(),before)

    def test_strict_finite_recipe_shapes(self):
        for args in ((True,DREAMS),(1,()),(1,(DREAMS[0],DREAMS[0])),(1,list(DREAMS)),(1,(' ',))):
            with self.subTest(args=args),self.assertRaises(ValueError):GenerateFromCandidates(*args)

    def test_pending_recipe_rejects_unknown_source_and_nonphysical_card(self):
        g=self.game();codec=FrameCodec(g.mechanics,self.r,origin_state=g.state)
        for e in (GenerateFromCandidates(1,DREAMS,999999),GenerateFromCandidates(1,('HERO_08bp',),g.state.players[1].hero_id)):
            with self.subTest(effect=e),self.assertRaises(ValueError):codec.encode(e)

    def test_rehashed_pending_recipe_rejects_unknown_source(self):
        g=self.game(hand=(P+'wait',));self.play(g,P+'wait');s=deepcopy(g.snapshot())
        for row in self.nodes(s):row['source_id']=999999
        self.reject(s)

    def test_generated_hand_outcome_is_private_to_owner(self):
        g=self.game();self.play(g);selected=self.cards(g)[0]
        own=json.dumps(g.for_player(1).observe());other=json.dumps(g.for_player(2).observe())
        self.assertIn(selected,own);self.assertNotIn(selected,other)
        for private in ('GenerateFromCandidates','resolution_frame','rng_state','card_ids'):
            self.assertNotIn(private,other)


if __name__=='__main__':unittest.main()
