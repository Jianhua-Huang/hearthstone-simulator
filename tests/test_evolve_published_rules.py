"""Execute the published Evolve cap and sparse Devolve tier fallbacks."""
import unittest

import test_m5_cross_zone as base
from hs_sim.engine import (ActivatedAbilitySpec, CardClass, CardType, Game, GenerationPolicy, Keyword,
    MinionScope, PlayCard, PoolQuery, SelectChoice, TransformMinionsInZones, Zone)
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, ModifyCost, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay, replay


def fixture(cost=15,delta=-1,*,members=('t4','t10','t12'),mode='normal',empty='skip',basis='printed',retain=None,wait=False):
    x=base.CrossZoneTests();x.setUp();x.card('origin',cost=cost)
    x.card('t4',cost=4)
    x.card('t10',cost=10,classes=(CardClass.MAGE,) if mode=='class' else (CardClass.NEUTRAL,))
    extra={}
    if mode=='titan':
        x.r.register_behavior('evolve.noop',lambda c:())
        extra={'keywords':(Keyword.TITAN,),
            'activated_abilities':tuple(ActivatedAbilitySpec(str(i),'evolve.noop') for i in range(3))}
    x.card('t12',cost=12,classes=(CardClass.WARRIOR,) if mode=='class' else (CardClass.NEUTRAL,),**extra)
    if mode=='unknown':x.card('unknown14',cost=14,executable=False)
    x.pool('tiers',members)
    query=(PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
        if mode=='class' else PoolQuery(kinds=(CardType.MINION,),collectible=True))
    def fail(c):raise ResolutionError('Deliberate Evolve rule failure')
    x.r.register_behavior('evolve.fail',fail)
    def body(c):
        request=TransformMinionsInZones(1,'tiers',delta,scope=MinionScope(query=PoolQuery(exclude_card_ids=('watch',))),
            query=query,cost_basis=basis,retain_cost_basis=retain,source_id=c.source_id,empty=empty)
        prefix=()
        if mode=='huge':prefix=(ModifyCost(c.state.players[1].board[0],CostSpec(set_to=2147483647)),)
        if mode=='rollback':return (*prefix,request,InvokeBehavior('evolve.fail',c.source_id,1))
        return (*prefix,request)
    x.script(body)
    if wait:
        def watch(c):
            # Only the first hand target pauses; later accepted tiers remain frozen.
            if c.event.target_id!=c.state.players[1].hand[0]:return ()
            second=c.state.players[1].hand[1]
            return (RequestChoice(1,(ChoiceOption('go','Change later local cost',
                (ModifyCost(second,CostSpec(set_to=20)),)),ChoiceOption('fail','Fail',
                (InvokeBehavior('evolve.fail',c.source_id,1),))),c.source_id),)
        x.watch(watch)
    return x


class EvolvePublishedRulesTests(unittest.TestCase):
    def game(self,**cfg):
        self.cfg=cfg;self.x=fixture(**cfg)
        return self.x.game(hand=('script',),deck=(),board=('origin',))
    def play(self,g):g.apply(PlayCard(1,next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='script')))
    def face(self,g):return g.state.entities[g.state.players[1].board[0]].card_id
    def portable(self,g):
        r=fixture(**self.cfg).r;s=g.snapshot();other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return other

    def test_a00_positive_tier_crossing_ten_caps_at_ten_instead_of_twelve(self):
        g=self.game(cost=9,delta=3);eid=g.state.players[1].board[0];self.play(g)
        self.assertEqual(self.face(g),'t10');self.assertEqual(g.state.players[1].board,[eid])

    def test_a01_ten_cost_evolves_to_ten_and_does_not_fall_back_to_lower(self):
        g=self.game(cost=10,delta=1);self.play(g);self.assertEqual(self.face(g),'t10')
        g=self.game(cost=10,delta=3,members=('t4',));rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.face(g),'origin');self.assertEqual(g._rng.getstate(),rng)

    def test_a02_greater_than_ten_evolves_at_its_original_cost(self):
        for delta in (1,5):
            with self.subTest(delta=delta):
                g=self.game(cost=12,delta=delta);self.play(g);self.assertEqual(self.face(g),'t12')

    def test_a03_same_face_is_a_real_transform_that_resets_old_material(self):
        g=self.game(cost=12,delta=1,members=('origin',));eid=g.state.players[1].board[0];epoch=g.state.entities[eid].zone_epoch
        self.play(g);self.assertEqual(self.face(g),'origin');self.assertEqual(g.state.entities[eid].zone_epoch,epoch+1)
        self.assertEqual(len([e for e in g.events if e.kind=='transformed']),1)

    def test_b00_devolve_finds_twelve_below_missing_fourteen_and_thirteen(self):
        g=self.game(cost=15,delta=-1);self.play(g);self.assertEqual(self.face(g),'t12')

    def test_b01_devolve_respects_the_full_negative_delta_before_falling_back(self):
        g=self.game(cost=15,delta=-5);self.play(g);self.assertEqual(self.face(g),'t10')
        g=self.game(cost=15,delta=-6);self.play(g);self.assertEqual(self.face(g),'t4')

    def test_b02_zero_delta_is_same_cost_without_evolve_cap_or_devolve_fallback(self):
        g=self.game(cost=12,delta=0);self.play(g);self.assertEqual(self.face(g),'t12')
        g=self.game(cost=9,delta=0,members=('t4',));rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.face(g),'origin');self.assertEqual(g._rng.getstate(),rng)

    def test_b03_large_local_cost_uses_sparse_pool_tiers_instead_of_integer_countdown(self):
        g=self.game(cost=15,delta=-1,mode='huge',basis='local');self.play(g);self.assertEqual(self.face(g),'t12')

    def test_b04_filtering_can_make_a_physical_higher_tier_unavailable(self):
        g=self.game(cost=15,delta=-1,mode='class');self.play(g);self.assertEqual(self.face(g),'t10')

    def test_b05_disallowed_special_only_tier_is_skipped_without_selecting_it(self):
        g=self.game(cost=15,delta=-1,mode='titan');self.play(g);self.assertEqual(self.face(g),'t10')

    def test_b06_unknown_eligible_higher_tier_is_an_error_not_a_reason_to_try_lower(self):
        g=self.game(cost=15,delta=-1,members=('unknown14','t12','t10'),mode='unknown');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_b07_no_eligible_tier_skips_without_rng_and_strict_empty_errors_after_search(self):
        g=self.game(cost=15,delta=-1,members=());rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.face(g),'origin');self.assertEqual(g._rng.getstate(),rng)
        g=self.game(cost=15,delta=-1,members=(),empty='error');s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Empty transformation'):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_c00_all_physical_zones_preserve_id_order_and_existing_retained_cost(self):
        self.cfg={'cost':15,'delta':-1,'retain':'printed'};x=fixture(**self.cfg);self.x=x
        g=x.game(hand=('script','origin'),deck=('origin',),board=('origin',));ids={z:tuple(getattr(g.state.players[1],z)) for z in ('hand','deck','board')}
        self.play(g)
        for z in ('hand','deck','board'):
            for eid in (i for i in ids[z] if g.state.entities[i].card_id!='script'):
                self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].cost),('t12',15))
        self.portable(g)

    def test_d00_wait_preserves_accepted_sparse_tier_when_later_local_cost_changes(self):
        self.cfg={'cost':15,'delta':-1,'basis':'local','wait':True};self.x=fixture(**self.cfg);self.x.card('second',cost=12)
        g=self.x.game(hand=('script','origin','second'),deck=(),board=('watch',));self.play(g)
        # Independent writer/reader fixtures contain the same additional source.
        reader=fixture(**self.cfg);reader.card('second',cost=12);s=g.snapshot();other=Game.from_snapshot(s,reader.r)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),reader.r).snapshot(),s)
        q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'Deliberate Evolve rule failure'):g.apply(SelectChoice(1,q.id,('fail',)))
        self.assertEqual(g.snapshot(),s)
        for game in (g,other):
            q=game.state.pending_choice;game.apply(SelectChoice(1,q.id,('go',)))
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['t12','t10'])

    def test_d01_late_failure_rolls_back_all_transforms_and_random(self):
        g=self.game(cost=15,delta=-1,mode='rollback');s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate Evolve rule failure'):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_d02_completed_sparse_devolve_restores_clones_replays_without_resampling(self):
        g=self.game(cost=15,delta=-1);self.play(g);self.portable(g)


if __name__=='__main__':unittest.main()
