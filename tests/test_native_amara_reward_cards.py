"""Native paid reward reuses the existing complete Story of Amara body."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_amara_reward_cards import BODY, EXISTING, REWARD, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (Buff, ChoiceOption, Destroy, GrantKeyword, Heal,
    InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import ChangeHeroMaxHealth, LoseHealth
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolDefinition,
    PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P = 'k147.'
FILL, POOL = P+'filler', P+'explicit-reward'
CONTEXT = GenerationContext(P+'complete-explicit-reward', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


def registry(mode=None):
    r = build_registry()
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, cost=1, attack=1, health=3, metadata=META))
    r.register_pool(PoolDefinition(POOL, 'k147-explicit-v1', CONTEXT.target_id, CONTEXT.mode,
        (PoolMember(REWARD),), complete=True))
    def hero(c): return c.state.players[c.player_id].hero_id
    def fail(c): raise ResolutionError('K147 deliberate observer failure')
    bodies = {
        'wound':lambda c:(LoseHealth(hero(c), 7, c.source_id),),
        'grow':lambda c:(ChangeHeroMaxHealth(c.player_id, 20, c.source_id),),
        'shrink':lambda c:(ChangeHeroMaxHealth(c.player_id, -20, c.source_id),),
        'heal':lambda c:(Heal(hero(c), 50, c.source_id),),
        'protect':lambda c:(Buff(hero(c), 3, 0, c.source_id),
            GrantKeyword(hero(c), Keyword.IMMUNE, c.source_id),
            GrantKeyword(hero(c), Keyword.DIVINE_SHIELD, c.source_id)),
        'summon':lambda c:(Summon(c.player_id, REWARD),),
        'generate':lambda c:(GenerateFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.MINION,), collectible=False), source_id=c.source_id),),
        'remove':lambda c:(Destroy(c.target_id, c.source_id),),
        'fail':fail}
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        if name == 'fail': continue
        kw = dict(targeting=TargetSpec(zones=(Zone.BOARD,),
            kinds=(CardType.MINION,), relation='friendly')) if name == 'remove' else {}
        r.register_card(CardDefinition(P+name, P+name, CardType.SPELL, metadata=META, on_play=P+name, **kw))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return (source is not None and source.card_id == REWARD and
                c.event.target_id == c.state.players[c.player_id].hero_id)
        def watch(c):
            target = c.state.entities[c.state.players[c.player_id].hero_id]
            if (target.health, target.max_health) != (40, 40):
                raise AssertionError('Observer saw an intermediate maximum/remaining health state')
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            if mode == 'wait':
                return (RequestChoice(c.player_id, (
                    ChoiceOption('ok', 'Continue'),
                    ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
            return ()
        r.register_trigger_condition(P+'eligible', eligible); r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, attack=1, health=3,
            metadata=META, limited_triggers=(LimitedTriggerSpec('stats_changed', P+'watch', P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(mode): return registry(mode)


class NativeAmaraRewardTests(unittest.TestCase):
    def game(self, hand=(REWARD,), *, mode=None, second_hand=()):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09', hand=hand, board=(P+'watch',) if mode else (),
                deck=(FILL,)*8, mana=50, max_mana=50, mana_cap=50, armor=17),
            PlayerSetup('HERO_08', hand=second_hand, deck=(FILL,)*8,
                mana=50, max_mana=50, mana_cap=50, armor=17)),
            seed=147, generation_context=CONTEXT), shared(mode))
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def play(self, g, cid, player=1, target=None):
        s=g.state; eid=next(i for i in s.players[player].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(player, eid, target_id=target,
            position=len(s.players[player].board) if s.entities[eid].kind==CardType.MINION else None))
        return eid
    def same(self, g, saved): self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(saved))
    def portable(self, g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.same(Game.from_snapshot(saved, registry(self.mode)), saved)
        self.same(g.clone(), saved); self.same(replay(build_replay(g), registry(self.mode)), saved)
        for player in (1,2):
            public=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('rng_state','resolution_frame','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
    def choose(self, g, key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_complete_five_records_ten_faces_actual_edges_and_exact_existing_body(self):
        from tools.card_batch import check_face
        d=load_batch(); rows={v['record']['id']:v for k in ('cards','existing_dependencies','evidence_only')for v in d[k]}
        self.assertEqual((len(rows),len(d['official_observations']),len(d['exact_parent_child_links'])),(5,10,4))
        faces={(o['card_id'],o['locale']):o['face'] for o in d['official_observations']}
        for o in d['official_observations']:check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for edge in d['exact_parent_child_links']:
            self.assertIn(edge['dbf_id'],faces[edge['parent'],edge['locale']]['childIds'])
        r=shared(None);card=r.card(REWARD)
        self.assertEqual((card.cost,card.attack,card.health,card.keywords,card.battlecry),(5,8,8,(Keyword.TAUNT,),BODY))
        self.assertFalse(card.metadata.collectible)
        self.assertEqual(canonical_digest(asdict(r.card(EXISTING))),d['existing_dependency_definition_pins'][EXISTING])
        self.assertEqual(r.card(EXISTING).on_play,BODY)
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated']or d['parents_implemented'])

    def test_real_paid_battlecry_assigns_one_atomic_transition_without_health_flows(self):
        g=self.game((P+'wound',P+'protect',REWARD),mode='observe')
        self.play(g,P+'wound');self.play(g,P+'protect');start=len(g.events);before=g.state
        source=self.play(g,REWARD);h=self.hero(g)
        self.assertEqual((h.health,h.max_health,h.armor,h.attack),(40,40,17,3))
        self.assertTrue({Keyword.IMMUNE,Keyword.DIVINE_SHIELD}<=h.keywords)
        self.assertEqual(g.state.players[1].mana,45)
        rows=g.state.hero_health_change_history[len(before.hero_health_change_history):]
        self.assertEqual(len(rows),1);self.assertEqual((rows[0].health_before,rows[0].health_after),(23,40))
        events=g.events[start:];stats=[e for e in events if e.kind=='stats_changed'and e.source_id==source]
        self.assertEqual(len(stats),1)
        self.assertFalse(any(e.kind in ('health_resolved','health_lost','max_health_gained','max_health_lost')for e in events))
        self.portable(g)

    def test_prior_maximum_above_and_below40_is_replaced_not_an_increment_or_clamp(self):
        for adjustment,expected in (('grow',50),('shrink',10)):
            with self.subTest(adjustment=adjustment):
                g=self.game((P+adjustment,REWARD));self.play(g,P+adjustment)
                self.assertEqual(self.hero(g).max_health,expected);self.play(g,REWARD)
                self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))

    def test_summon_and_generation_do_not_run_battlecry_but_generated_card_can_be_paid(self):
        for entry in ('summon','generate'):
            with self.subTest(entry=entry):
                g=self.game((P+'wound',P+entry));self.play(g,P+'wound');self.play(g,P+entry)
                self.assertEqual((self.hero(g).health,self.hero(g).max_health),(23,30))
                if entry=='generate':
                    self.play(g,REWARD);self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
                else:
                    token=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==REWARD)
                    self.assertEqual((token.attack,token.health,token.keywords),(8,8,{Keyword.TAUNT}))

    def test_committed_assignment_wait_restores_and_bad_continuation_rolls_back_locally(self):
        g=self.game((P+'wound',REWARD),mode='wait');self.play(g,P+'wound');self.play(g,REWARD)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40));self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.same(g,saved);self.choose(g,'ok');self.portable(g)

    def test_observer_exception_rolls_back_entire_paid_card_and_original_hero_stats(self):
        g=self.game((P+'wound',REWARD),mode='fail');self.play(g,P+'wound');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,REWARD)
        self.same(g,saved)

    def test_player2_assigns_current_own_hero_and_preserves_other_seat(self):
        g=self.game((),second_hand=(P+'wound',REWARD));g.apply(EndTurn(1))
        self.play(g,P+'wound',2);source=self.play(g,REWARD,2)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(30,30))
        self.assertEqual((self.hero(g,2).health,self.hero(g,2).max_health,self.hero(g,2).armor),(40,40,17))
        event=next(e for e in g.events if e.kind=='stats_changed'and e.source_id==source)
        self.assertEqual((event.target_id,dict(event.data)['hero_health_transition'][0]),(self.hero(g,2).id,2))
        self.portable(g)

    def test_source_death_keeps_maximum_and_later_real_healing_uses40_cap(self):
        g=self.game((REWARD,P+'remove',P+'wound',P+'heal'));source=self.play(g,REWARD)
        self.play(g,P+'remove',target=source);self.assertEqual(self.hero(g).max_health,40)
        self.play(g,P+'wound');self.assertEqual(self.hero(g).health,33)
        self.play(g,P+'heal');self.assertEqual((self.hero(g).health,self.hero(g).max_health),(40,40))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)


if __name__=='__main__':unittest.main()
