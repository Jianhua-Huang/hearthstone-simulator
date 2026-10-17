"""Original Location entry material, including zero, uses shared death/combat."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_hand_size_summon_attack_cards import SPIRE, DEMON, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Rarity, Ruleset, Scenario, SelectChoice, SnapshotError,
    SummonStats, TargetSpec, UseLocation, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.model import AuraSpec, LimitedTriggerSpec, Resource, SummonQuantitySpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.zones import CardReference

P='k148.'
FILL,TANK,DORMANT,LOCATION=(P+n for n in ('filler','tank','dormant','location'))
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


def registry(mode=None):
    r=build_registry()
    r.register_behavior(P+'noop',lambda c:())
    def fail(c):raise ResolutionError('K148 deliberate entry failure')
    r.register_behavior(P+'fail',fail)
    for cid,kw in ((FILL,dict(attack=1,health=3)),(TANK,dict(health=30)),
            (DORMANT,dict(health=20,dormant_turns=20)),
            (P+'aura',dict(health=4,auras=(AuraSpec(attack=1,health=1),))),
            (P+'twice',dict(health=5,summon_quantities=(SummonQuantitySpec(),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,metadata=META,**kw))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=P+'noop',metadata=META))
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id,stats=SummonStats(0,0),cause=SummonCause.capture(c)),),
        'resurrect':lambda c:(ResurrectMinion(c.player_id,c.state.death_history[-1].id,
            source_id=c.source_id,stats=SummonStats(0,0),cause=SummonCause.capture(c)),),
        'reenter':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id,cause=SummonCause.capture(c)),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        if name=='reenter':continue
        kw={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')} if name in ('kill','copy') else {}
        r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name,metadata=META,**kw))
    if mode:
        event='attack_declared'if mode=='combat'else'minion_summoned'
        def matching(c):
            eid=c.event.source_id if mode=='combat'else c.event.target_id
            e=c.state.entities.get(eid)
            if e is None:return None
            return next((root for root in c.state.card_summon_history
                if root.request.cause.source.card_id==SPIRE and any(d.entity is not None and
                    (d.entity.entity_id,d.entity.entered_order)==(eid,e.entered_order)for d in root.deliveries)),None)
        r.register_trigger_condition(P+'eligible',lambda c:matching(c)is not None)
        def watch(c):
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            eid=c.event.source_id if mode=='combat'else c.event.target_id
            e=c.state.entities[eid];root=matching(c)
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok',f'{e.attack}/{e.health}'),
                ChoiceOption('bad','Fail after hand change',(AddToHand(c.player_id,FILL,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))),
                ChoiceOption('hand','Add another hand card',(AddToHand(c.player_id,FILL,c.source_id),)),
                ChoiceOption('reenter','Move original away and reenter',(
                    ReturnToHand(eid),InvokeBehavior(P+'reenter',c.source_id,c.player_id,target_id=eid))),
                ChoiceOption('source','Remove original Location',(DestroyLocation(root.request.cause.source.entity_id,c.source_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch',P+'watch',CardType.WEAPON,durability=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',P+'eligible'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared(mode):return registry(mode)


class NativeHandSizeSummonAttackTests(unittest.TestCase):
    def game(self,hand=(),*,board=(SPIRE,),enemy=(TANK,),second_hand=(),mode=None,rules=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,
            deck=(FILL,)*8,mana=50,max_mana=50,mana_cap=50,weapon_card_id=P+'watch'if mode else None),
            PlayerSetup('HERO_08',hand=second_hand,board=enemy,deck=(FILL,)*8,
                mana=50,max_mana=50,mana_cap=50)),seed=148),shared(mode),ruleset=rules or Ruleset())
    def play(self,g,cid,target=None):
        s=g.state;p=s.active_player;eid=next(i for i in s.players[p].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target_id=target,position=len(s.players[p].board)
            if s.entities[eid].kind in (CardType.MINION,CardType.LOCATION)else None));return eid
    def location(self,g,player=1):return next(i for i in g.state.players[player].board if g.state.entities[i].card_id==SPIRE)
    def use(self,g,player=1):
        eid=self.location(g,player);g.apply(UseLocation(player,eid));return eid
    def demons(self,g):return [e for e in g.state.entities.values()if e.card_id==DEMON]
    def roots(self,g):return [r for r in g.state.card_summon_history if r.request.cause.source.card_id==SPIRE]
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def same(self,g,saved):self.assertEqual(canonical_hash(g.snapshot()),canonical_hash(saved))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.same(Game.from_snapshot(saved,registry(self.mode)),saved)
        self.same(g.clone(),saved);self.same(replay(build_replay(g),registry(self.mode)),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('rng_state','resolution_frame','card_summon_history','followup','behavior_id'):
                self.assertNotIn('"'+key+'"',public)

    def test_full_three_raw_rows_four_primary_faces_two_edges_and_no_inferred_immune(self):
        from tools.card_batch import check_face
        d=load_batch();rows={v['record']['id']:v for k in ('cards','dependencies','evidence_only')for v in d[k]}
        self.assertEqual((len(rows),len(d['official_observations'])),(3,4))
        faces={(o['card_id'],o['locale']):o['face']for o in d['official_observations']}
        for o in d['official_observations']:check_face(rows[o['card_id']]['record'],o['face'],o['locale'])
        for edge in d['exact_parent_child_links']:self.assertIn(edge['dbf_id'],faces[edge['parent'],edge['locale']]['childIds'])
        r=shared(None);self.assertEqual((r.card(SPIRE).cost,r.card(SPIRE).durability),(5,2))
        self.assertEqual((r.card(DEMON).attack,r.card(DEMON).health,r.card(DEMON).keywords),(1,1,()))
        self.assertEqual(r.card(DEMON).metadata.tribes,('demon',));self.assertFalse(d['cn_calibrated']or d['formal_pool_complete'])
        self.assertEqual(d['raw_only_evidence_ids'],['JAIL_511e'])

    def test_zero_typed_stats_allow_nonnegative_integers_but_not_negative_or_boolean(self):
        self.assertEqual(SummonStats(0,0).health,0);self.assertIsNone(SummonStats(health=0).attack)
        for pair in ((None,None),(1,-1),(-1,0),(True,0),(0,False),(0,0.0)):
            with self.subTest(pair=pair),self.assertRaises(ValueError):SummonStats(*pair)

    def test_paid_location_uses_remaining_hand_once_and_actual_random_minion_combat(self):
        g=self.game((SPIRE,FILL,FILL,FILL),board=());source=self.play(g,SPIRE)
        self.assertEqual(g.state.players[1].mana,45);self.use(g)
        demon,=self.demons(g);tank=next(e for e in g.state.entities.values()if e.card_id==TANK)
        self.assertEqual((demon.attack,demon.health,tank.damage),(3,3,3))
        self.assertEqual((g.state.entities[source].durability,g.state.players[1].mana),(1,45))
        self.assertGreater(g.state.entities[source].location_cooldown,0);self.assertFalse(demon.keywords)
        self.assertEqual(self.roots(g)[0].request.materials[0].stats,SummonStats(3,3));self.portable(g)

    def test_real_empty_hand_creates0_0_then_ordinary_death_and_corpse_without_rng(self):
        g=self.game((SPIRE,),board=());self.play(g,SPIRE);before=g.snapshot()['rng_state'];self.use(g)
        demon,=self.demons(g);self.assertEqual((demon.attack,demon.max_health,demon.zone),(0,0,Zone.GRAVEYARD))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(len([r for r in g.state.successful_summon_history if r.entity_id==demon.id]),1)
        self.assertFalse(any(e.kind=='attack_declared'for e in g.events));self.assertEqual(g.snapshot()['rng_state'],before)
        self.portable(g)

    def test_existing_aura_can_keep_zero_local_material_alive_before_first_entry(self):
        g=self.game(board=(SPIRE,P+'aura'));self.use(g);demon,=self.demons(g)
        self.assertEqual((demon.attack,demon.health,demon.zone),(1,1,Zone.BOARD))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertTrue(any(e.kind=='attack_declared'and e.source_id==demon.id for e in g.events))

    def test_quantity_extras_each_keep_zero_material_and_normal_independent_death(self):
        g=self.game(board=(SPIRE,P+'twice'));before=g.snapshot()['rng_state'];self.use(g)
        self.assertEqual(len(self.demons(g)),2);self.assertTrue(all(e.zone==Zone.GRAVEYARD for e in self.demons(g)))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],2)
        root,=self.roots(g);self.assertEqual((root.plan.total,len(root.deliveries),root.status),(2,2,'completed'))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_no_enemy_minion_ignores_hero_dormant_and_location_without_rng(self):
        g=self.game((FILL,FILL),enemy=(DORMANT,LOCATION));before=g.snapshot()['rng_state'];self.use(g)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(any(e.kind=='attack_declared'for e in g.events))
        self.assertEqual(self.demons(g)[0].health,2)

    def test_full_board_uses_native_activation_but_no_delivery_or_random_attack(self):
        g=self.game((FILL,),board=(SPIRE,)+(FILL,)*6);before=g.snapshot()['rng_state'];source=self.use(g)
        self.assertFalse(self.demons(g));self.assertEqual(self.roots(g)[0].status,'skipped')
        self.assertEqual((g.state.entities[source].durability,g.snapshot()['rng_state']),(1,before))

    def test_entry_wait_freezes_original_hand_stats_and_restores_exact_remaining_work(self):
        g=self.game((FILL,FILL),mode='entry');self.use(g)
        self.assertEqual(g.state.pending_choice.options[0].label,'2/2');self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.same(g,saved);self.choose(g,'hand')
        self.assertEqual((self.demons(g)[0].attack,len(g.state.players[1].hand)),(2,3));self.portable(g)

    def test_original_minion_reentry_does_not_rebind_or_attack_with_new_residence(self):
        g=self.game((FILL,),mode='entry');self.use(g);demon=self.demons(g)[0];original=demon.entered_order
        before=g.snapshot()['rng_state'];self.choose(g,'reenter');current=g.state.entities[demon.id]
        self.assertNotEqual(current.entered_order,original);self.assertEqual(current.zone,Zone.BOARD)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(any(e.kind=='attack_declared'for e in g.events))
        self.portable(g)

    def test_original_location_removed_during_entry_does_not_cancel_accepted_body_attack(self):
        g=self.game((FILL,),mode='entry');source=self.use(g);self.choose(g,'source')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertTrue(any(e.kind=='attack_declared'for e in g.events));self.portable(g)

    def test_entry_failure_rolls_back_use_charge_material_rng_and_history(self):
        g=self.game((FILL,),mode='fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.use(g)
        self.same(g,saved)

    def test_second_player_uses_own_hand_and_actual_opponent_not_original_seat(self):
        g=self.game(board=(TANK,),enemy=(SPIRE,),second_hand=(FILL,FILL));g.apply(EndTurn(1))
        size=len(g.state.players[2].hand);self.use(g,2);demon,=self.demons(g)
        self.assertEqual((demon.controller,demon.attack),(2,size));root,=self.roots(g)
        self.assertEqual(root.request.player_id,2);self.portable(g)

    def test_shared_copy_and_resurrection_accept_zero_before_entry_not_post_set_stats(self):
        for route in ('copy','resurrect'):
            with self.subTest(route=route):
                hand=(P+'copy',)if route=='copy'else(P+'kill',P+'resurrect')
                g=self.game(hand,board=(FILL,),enemy=());original=g.state.players[1].board[0]
                if route=='resurrect':self.play(g,P+'kill',original)
                old=set(g.state.entities);self.play(g,P+route,original if route=='copy'else None)
                created=[e for eid,e in g.state.entities.items()if eid not in old and e.card_id==FILL]
                self.assertEqual(len(created),1);self.assertEqual((created[0].max_health,created[0].zone),(0,Zone.GRAVEYARD))
                if route=='copy':self.assertEqual(g.state.entities[original].health,3)
                self.portable(g)

    def test_zero_entry_first_observer_sees0_0_and_waiting_snapshot_keeps_old_schema_rejected(self):
        g=self.game(mode='entry');self.use(g)
        self.assertEqual(g.state.pending_choice.options[0].label,'0/0');self.portable(g)
        saved=g.snapshot();saved['schema_version']=353
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode))
        self.choose(g,'ok');self.assertEqual(self.demons(g)[0].zone,Zone.GRAVEYARD)

    def test_actual_combat_wait_restores_without_another_random_target_or_hand_rescale(self):
        g=self.game((FILL,FILL),mode='combat');self.use(g);self.portable(g)
        before=g.snapshot()['rng_state'];self.choose(g,'hand')
        self.assertEqual((self.demons(g)[0].attack,g.snapshot()['rng_state']),(2,before));self.portable(g)


if __name__=='__main__':unittest.main()
