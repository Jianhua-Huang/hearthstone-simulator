"""Complete fixed family and bounded fill requests through ordinary pipelines."""
import json,unittest
from random import Random
from hs_sim.cards import build_registry
from hs_sim.cards.fixed_companion_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Ruleset,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import canonical_digest

ANIMAL='CORE_NEW1_031';CALL='CORE_OG_211';HAL='CORE_TRL_900';LYNX='TRL_348t'
ORDER=('NEW1_034','NEW1_033','NEW1_032');YETI='CORE_CS2_182';KHADGAR='CORE_DAL_575'


def registry():
    r=build_registry()
    def fill(c):return(FillHandWithCard(c.player_id,LYNX,c.source_id),)
    scripts=dict(fill=fill,bad=lambda c:(*fill(c),AddToHand(c.player_id,'unknown.k34')),
        unknown=lambda c:(AddToHand(c.player_id,YETI,c.source_id),FillHandWithCard(c.player_id,'unknown.k34',c.source_id)),
        budget=lambda c:(SetHandCapacity(c.player_id,2000),*fill(c)),
        wait=lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Fill',fill(c)),),c.source_id),),
        fail=lambda c:(AddToHand(c.player_id,'unknown.k34'),))
    for key,fn in scripts.items():
        r.register_behavior('k34.'+key,fn)
        if key!='fail':r.register_card(CardDefinition('k34.'+key,key,CardType.SPELL,on_play='k34.'+key))
    def watch(c):
        if c.event.kind=='card_added_to_hand':
            if c.state.entities[c.event.target_id].card_id!=LYNX:return()
            count=sum(c.state.entities[i].card_id==LYNX for i in c.state.players[c.player_id].hand)
        else:
            if c.state.entities[c.event.target_id].card_id not in ORDER:return()
            count=sum(c.state.entities[i].card_id in ORDER for i in c.state.players[c.player_id].board)
        if count!=1:return()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),
            ChoiceOption('shrink','Reduce actual hand capacity',(SetHandCapacity(c.player_id,1),)),
            ChoiceOption('expand','Increase actual hand capacity',(SetHandCapacity(c.player_id,14),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('k34.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k34.watch',watch)
    for event,key in(('card_added_to_hand','handwatch'),('minion_summoned','summonwatch')):
        r.register_card(CardDefinition('k34.'+key,key,CardType.MINION,health=8,triggers=(TriggerSpec(event,'k34.watch'),)))
    return r


class FixedCompanionCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,cap=None,rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hand_cap=cap,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=434),self.r,ruleset=rules)
    def play(self,g,cid):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,None,len(g.state.players[p].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('resolution_frame','card_summon_history','hand_entry_history','rng_state','SummonEntryMaterial'):
                self.assertNotIn('"'+key+'"',public)

    def test_complete_pins_exact_dependency_identities_and_noncollectible_flags(self):
        data=load_batch();self.assertEqual(len(data['cards']),7)
        for row in data['cards']+data['historical_identity_evidence']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(tuple(data['companion_order']),ORDER)
        for cid in ORDER+(LYNX,):self.assertFalse(self.r.card(cid).metadata.collectible)
        self.assertEqual(self.r.card(LYNX).keywords,(Keyword.RUSH,));self.assertIn(Keyword.RUSH,self.r.card(HAL).keywords)
        self.assertEqual((self.r.card(HAL).cost,self.r.card(HAL).attack,self.r.card(HAL).health),(4,4,2))

    def test_animal_uniform_fixed_three_materials_use_actual_rng_and_pay_once(self):
        g=self.game((ANIMAL,));s=g.snapshot()['rng_state'];rng=Random();rng.setstate((s[0],tuple(s[1]),s[2]));expected=ORDER[rng.randrange(3)]
        source=self.play(g,ANIMAL);self.assertEqual(self.board(g),[expected]);self.assertEqual(g.state.players[1].mana,37)
        root=g.state.card_summon_history[-1];self.assertEqual(tuple(m.card_id for m in root.request.materials),ORDER)
        self.assertEqual(root.request.cause.source.entity_id,source);self.assertEqual(root.request.cause.cast_id,g.state.cast_history[-1].id);self.portable(g)

    def test_animal_full_board_does_not_select_or_consume_rng(self):
        g=self.game((ANIMAL,),(YETI,)*7);rng=g.snapshot()['rng_state'];self.play(g,ANIMAL)
        self.assertEqual(self.board(g),[YETI]*7);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_animal_accepted_quantity_extras_keep_same_selected_companion(self):
        g=self.game((ANIMAL,),(KHADGAR,));self.play(g,ANIMAL);companions=[c for c in self.board(g)if c in ORDER]
        self.assertEqual(len(companions),2);self.assertEqual(companions[0],companions[1]);self.portable(g)

    def test_call_three_deterministic_requests_and_real_leokk_aura(self):
        g=self.game((CALL,));rng=g.snapshot()['rng_state'];self.play(g,CALL)
        self.assertEqual(self.board(g),list(ORDER));self.assertEqual(g.snapshot()['rng_state'],rng)
        bodies=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual([e.attack for e in bodies],[5,2,5]);self.assertIn(Keyword.CHARGE,bodies[0].keywords);self.assertIn(Keyword.TAUNT,bodies[2].keywords)
        self.assertEqual(g.state.players[1].mana,32);self.portable(g)

    def test_call_fixed_order_respects_each_remaining_board_slot(self):
        for count in(4,5,6,7):
            g=self.game((CALL,),(YETI,)*count);self.play(g,CALL)
            self.assertEqual(self.board(g)[count:],list(ORDER[:7-count]))

    def test_call_quantity_is_per_request_and_retains_family_order(self):
        g=self.game((CALL,),(KHADGAR,));self.play(g,CALL)
        self.assertEqual(self.board(g),[KHADGAR,ORDER[0],ORDER[0],ORDER[1],ORDER[1],ORDER[2],ORDER[2]])

    def test_call_waiting_keeps_accepted_tail_and_independent_restore(self):
        g=self.game((CALL,),('k34.summonwatch',));self.play(g,CALL);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.board(g)[1:],[ORDER[0]]);self.portable(g);self.choose(g)
        self.assertEqual(self.board(g)[1:],list(ORDER));self.portable(g)

    def test_random_companion_wait_does_not_resample_after_failed_choice(self):
        g=self.game((ANIMAL,),('k34.summonwatch',));self.play(g,ANIMAL);saved=g.snapshot();chosen=self.board(g)[1]
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.portable(g);self.choose(g);self.assertEqual(self.board(g)[1],chosen)

    def test_huffer_can_attack_hero_immediately(self):
        g=self.game((CALL,));self.play(g,CALL);huffer=g.state.players[1].board[0]
        g.apply(Attack(1,huffer,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)

    def test_halazzi_fills_current_remaining_hand_with_complete_lynxes(self):
        g=self.game((HAL,YETI,YETI));source=self.play(g,HAL)
        self.assertEqual(self.hand(g),[YETI,YETI]+[LYNX]*8);self.assertEqual(g.state.players[1].mana,36)
        self.assertEqual(self.board(g),[HAL]);self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)
        self.assertFalse(g.state.draw_history);self.portable(g)

    def test_fill_uses_actual_player_override_or_rules_default_capacity(self):
        for cap,rules,expected in((5,None,5),(None,Ruleset(max_hand=4),4),(7,Ruleset(max_hand=4),7)):
            g=self.game((HAL,),cap=cap,rules=rules);self.play(g,HAL)
            self.assertEqual(self.hand(g),[LYNX]*expected);self.portable(g)

    def test_halazzi_from_full_starting_hand_creates_exactly_one_lynx(self):
        g=self.game((HAL,)+(YETI,)*9);self.play(g,HAL)
        self.assertEqual(self.hand(g),[YETI]*9+[LYNX]);self.assertFalse(any(e.kind=='card_burned'for e in g.events))

    def test_lynx_rush_allows_minion_attack_and_rejects_first_turn_hero(self):
        g=self.game((HAL,),enemy=(YETI,));self.play(g,HAL);eid=self.play(g,LYNX)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,g.state.players[2].hero_id))
        g.apply(Attack(1,eid,g.state.players[2].board[0]));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,4)

    def test_fill_waiting_recovery_preserves_original_finite_slot_count(self):
        g=self.game((HAL,),('k34.handwatch',),cap=4);self.play(g,HAL)
        self.assertEqual(self.hand(g),[LYNX]);self.portable(g);self.choose(g,'expand')
        self.assertEqual(g.state.players[1].hand_cap,14);self.assertEqual(self.hand(g),[LYNX]*4);self.portable(g)

    def test_fill_later_smaller_capacity_uses_existing_burn_without_refilling_loop(self):
        g=self.game((HAL,),('k34.handwatch',),cap=4);self.play(g,HAL);self.choose(g,'shrink')
        self.assertEqual(self.hand(g),[LYNX]);burned=[e for e in g.state.entities.values()if e.card_id==LYNX and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),3);self.assertFalse(g.state.discard_history);self.assertFalse(g.state.death_history);self.portable(g)

    def test_fill_failed_choice_restores_committed_generation_and_original_tail(self):
        g=self.game((HAL,),('k34.handwatch',),cap=4);self.play(g,HAL);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(self.hand(g),[LYNX]*4)

    def test_fill_request_itself_can_be_queued_before_choice_and_roundtrip_codec(self):
        g=self.game(('k34.wait',),cap=4);self.play(g,'k34.wait');self.assertFalse(self.hand(g));self.portable(g)
        codec=FrameCodec(g.mechanics,self.r,origin_state=g.state);effect=FillHandWithCard(1,LYNX)
        self.assertEqual(codec.decode(codec.encode(effect)),effect);self.choose(g);self.assertEqual(self.hand(g),[LYNX]*4);self.portable(g)

    def test_fill_later_transaction_error_restores_all_created_entities_and_rng(self):
        g=self.game(('k34.bad',),cap=4);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k34.bad')
        self.assertEqual(g.snapshot(),saved)

    def test_fill_validates_unknown_definition_even_when_effective_hand_is_full(self):
        g=self.game(('k34.unknown',YETI,YETI,YETI),cap=4);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k34.unknown')
        self.assertEqual(g.snapshot(),saved)

    def test_fill_budget_rejection_rolls_back_capacity_change_and_payment(self):
        g=self.game(('k34.budget',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k34.budget')
        self.assertEqual(g.snapshot(),saved)

    def test_fill_constructor_rejects_unknown_shapes(self):
        for args in((0,LYNX),(True,LYNX),(1,''),(1,LYNX,0)):
            with self.assertRaises(ValueError):FillHandWithCard(*args)


if __name__=='__main__':unittest.main()
