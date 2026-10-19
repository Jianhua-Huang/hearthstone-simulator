"""Malorne's primary named cycle, original Imbue count and ordinary delivery."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.wild_god_discovery_card import CARD, GODS, POOL_ID, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior, RandomDamage,
    ReplaceHeroPower, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.imbue import Imbue, imbue_count
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial

P='malorne.test.'
CTX=GenerationContext('malorne-complete-explicit-experimental-domain','experimental')
PICKS=('EDR_209','EDR_471','EDR_480')
FILL='CS2_182'
IMBUE={n:P+'imbue.'+str(n)for n in (3,4,5)}
RESET,SUMMON,WATCH,UNKNOWN=(P+x for x in ('reset','summon','watch','unknown'))


@lru_cache(maxsize=None)
def registry(role,mode='normal'):
    assert role in ('writer','reader')
    r=build_registry()
    for n,cid in IMBUE.items():
        r.register_behavior(cid,lambda c,n=n:(Imbue(c.player_id,c.source_id,n),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior(RESET,lambda c:(ReplaceHeroPower(c.player_id,'HERO_08bp'),))
    r.register_card(CardDefinition(RESET,RESET,CardType.SPELL,on_play=RESET))
    r.register_behavior(SUMMON,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),))
    r.register_card(CardDefinition(SUMMON,SUMMON,CardType.SPELL,on_play=SUMMON))
    # Full actual named membership stays in the card query. The fixture's
    # explicit experimental domain is a slice, never the formal Standard pool.
    r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,10,r.card(PICKS[0]).metadata,
        battlecry=False,deathrattle=False,choose_one=False,attack=10))
    members=(*PICKS,CARD,FILL,UNKNOWN)
    if mode=='short':members=(PICKS[0],CARD,FILL,UNKNOWN)
    elif mode=='empty':members=(CARD,FILL,UNKNOWN)
    elif mode=='all':members=(*GODS,CARD,FILL,UNKNOWN)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,P+'domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ResolutionError('Malorne deliberate rollback')
    r.register_behavior(P+'fail',fail)
    if mode in ('offer','acquire','fail','fill'):
        def watch(c):
            e=c.event
            if mode in ('offer','fill'):
                if e.source_id is None or c.state.entities[e.source_id].card_id!=CARD:return ()
                if mode=='fill':return (AddToHand(c.player_id,FILL,c.source_id),)
                return (Imbue(c.player_id,c.source_id),)if imbue_count(c.state,c.player_id)==3 else ()
            if e.target_id is None or c.state.entities[e.target_id].card_id not in GODS:return ()
            bad=(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
            if mode=='fail':return bad
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',bad)),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
            triggers=(TriggerSpec('choice_selected'if mode in ('offer','fill')else 'card_added_to_hand',WATCH),)))
    r.validate();r.freeze();return r


class WildGodDiscoveryTests(unittest.TestCase):
    def game(self,hand=(CARD,),*,mode='normal',board=(),enemy_hand=(),hero='HERO_08'):
        if mode in ('offer','acquire','fail','fill'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(FILL,)*15,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(FILL,)*15,mana=10,max_mana=10)),seed=250888,generation_context=CTX),registry('writer',mode))
    def play(self,g,cid=CARD):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def pick(self,g,key=None):
        q=g.state.pending_choice;o=next(o for o in q.options if o.id==key)if key else q.options[0]
        g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id
    def cost(self,g,cid,pid=1):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return quote_cost(g.state,g.registry,g.state.entities[eid]).amount
    def portable(self,g,mode='normal'):
        r=registry('reader'if g.registry is registry('writer',mode)else 'writer',mode)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved);return other

    def test_a00_complete_primary_cycle_is_eleven_class_roots_not_related_tokens_or_malorne(self):
        from tools.card_batch import check_face
        data=load_batch();raw=data['cards'][0]['record']
        for x in data['official_observations']:check_face(raw,x['face'],x['locale'])
        self.assertEqual(len(data['pool_inventory']),11);self.assertEqual(len(data['related_non_candidates']),4)
        self.assertNotIn(CARD,GODS);self.assertEqual(len({x['record']['tags']['CLASS']for x in data['pool_inventory']}),11)

    def test_b00_normal_discovery_is_exactly_named_foreign_gods_with_printed_cost_and_one_payment(self):
        g=self.game();self.play(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(PICKS))
        cid=self.pick(g);self.assertEqual(self.cost(g,cid),g.registry.card(cid).cost)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_b01_three_four_and_five_actual_imbue_records_choose_the_threshold_correctly(self):
        for n in (3,4,5):
            with self.subTest(n=n):
                g=self.game((IMBUE[n],CARD));self.play(g,IMBUE[n]);self.assertEqual(imbue_count(g.state,1),n)
                self.play(g);cid=self.pick(g);self.assertEqual(self.cost(g,cid),1 if n>=4 else g.registry.card(cid).cost)

    def test_c00_enemy_imbues_do_not_discount_the_original_owner(self):
        g=self.game(enemy_hand=(IMBUE[4],));g.apply(EndTurn(1));self.play(g,IMBUE[4]);g.apply(EndTurn(2))
        self.play(g);cid=self.pick(g);self.assertEqual(imbue_count(g.state,1),0)
        self.assertEqual(self.cost(g,cid),g.registry.card(cid).cost)

    def test_c01_second_player_uses_own_original_history_and_receives_own_one_cost_god(self):
        g=self.game(hand=(),enemy_hand=(IMBUE[4],CARD));g.apply(EndTurn(1));self.play(g,IMBUE[4]);self.play(g)
        cid=self.pick(g);self.assertEqual(self.cost(g,cid,2),1)
        self.assertFalse(any(g.state.entities[i].card_id in GODS for i in g.state.players[1].hand));self.portable(g)

    def test_c02_inherited_no_effect_class_count_policy_is_explicit_and_not_power_level(self):
        g=self.game((IMBUE[4],CARD),hero='HERO_01');self.play(g,IMBUE[4])
        self.assertEqual(imbue_count(g.state,1),4);self.assertEqual(imbue_count(g.state,1,applied_only=True),0)
        self.play(g);cid=self.pick(g);self.assertEqual(self.cost(g,cid),1)

    def test_c03_power_replacement_does_not_erase_the_original_imbue_history(self):
        g=self.game((IMBUE[4],RESET,CARD));self.play(g,IMBUE[4]);self.play(g,RESET);self.play(g)
        cid=self.pick(g);self.assertEqual(self.cost(g,cid),1)

    def test_d00_old_offer_keeps_original_cost_while_next_actual_battlecry_sees_new_imbue(self):
        g=self.game((IMBUE[3],CARD),mode='offer',board=('TIME_064',));self.play(g,IMBUE[3]);self.play(g)
        first=self.pick(g);self.assertEqual(imbue_count(g.state,1),4);self.assertEqual(self.cost(g,first),g.registry.card(first).cost)
        self.assertIsNotNone(g.state.pending_choice)
        prior=set(g.state.entities);second=self.pick(g)
        added=[e for eid,e in g.state.entities.items()if eid not in prior and e.card_id==second]
        self.assertEqual(len(added),1);self.assertEqual(quote_cost(g.state,g.registry,added[0]).amount,1)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(len(g.state.card_discovery_history),2)

    def test_d01_ordinary_summon_does_not_discover_or_invent_imbue(self):
        g=self.game((SUMMON,));self.play(g,SUMMON)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history);self.assertEqual(imbue_count(g.state,1),0)

    def test_e00_original_discovery_wait_restores_frozen_one_cost_recipe(self):
        g=self.game((IMBUE[4],CARD));self.play(g,IMBUE[4]);self.play(g);g=self.portable(g)
        cid=self.pick(g);self.assertEqual(self.cost(g,cid),1)

    def test_e01_acquisition_wait_already_has_one_cost_and_recovers_without_redelivery(self):
        g=self.game((IMBUE[4],CARD),mode='acquire');self.play(g,IMBUE[4]);self.play(g);cid=self.pick(g)
        self.assertEqual(self.cost(g,cid),1);g=self.portable(g,'acquire');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'fail')
        self.assertEqual(g.snapshot(),before);self.pick(g,'ok');self.assertEqual(len(g.state.card_discovery_history),1)

    def test_e02_immediate_acquisition_failure_restores_original_offer_rng_and_payment(self):
        g=self.game((IMBUE[4],CARD),mode='fail');self.play(g,IMBUE[4]);self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,2)

    def test_f00_full_hand_burn_still_commits_the_real_selection_once(self):
        g=self.game((CARD,*((FILL,)*9)),mode='fill');self.play(g);self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(sum(e.kind=='card_burned'for e in g._events),1)

    def test_f01_empty_short_and_unimplemented_actual_gods_never_fallback_to_other_legendary_beasts(self):
        g=self.game(mode='empty');rng=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game(mode='short');self.play(g);self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),(PICKS[0],));self.pick(g)
        for mode in ('all','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_g00_original_offers_history_and_cost_continuations_stay_out_of_enemy_view(self):
        g=self.game((IMBUE[4],CARD));self.play(g,IMBUE[4]);self.play(g)
        enemy=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for cid in PICKS:self.assertNotIn(cid,enemy)
        self.pick(g)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"original_offer"','"resolution_frame"','"rng_state"'):self.assertNotIn(key,wire)


if __name__=='__main__':unittest.main()
