"""Actual complete token chains, original swaps and two physical spell draws."""
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_zone_token_draw as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,Scenario
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,GainArmor,InvokeBehavior,RandomDamage,RequestChoice,
    ReturnToHand,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,LimitedTriggerSpec,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

LYNN,FLIK,TICKATUS,KANGOR,POZZIK,WAX,MANKRIK,BOOM,MAXIMA,BALINDA=native.ROOTS
CORRUPTED,BOT,CANDLE,WIFE,RAGE,BOMB=native.DEPENDENCIES
BOOMBOT=native.EXISTING[0]
P='k730.'
A,SMALL,HIGH,DONOR,SAME_A,SAME_B,SAME_SLEEP=(P+x for x in('a','small','high','donor','same_a','same_b','same_sleep'))
NOOP,DRAW,KILL,KILL_FILL,EARLY_FILL,HUSH,TO_SAME,MOVE_BOT,SUMMON,SLUDGE,SPELL8,SPELL3,SPELL0,FAKE_BOMB=(P+x for x in
    ('noop','draw','kill','kill_fill','early_fill','hush','to_same','move_bot','summon','sludge','spell8','spell3','spell0','fake_bomb'))
WAIT_GIFT,WAIT_RETURN,WAIT_RECRUIT,WAIT_DRAW,FAIL,QUANTITY=(P+x for x in('wait_gift','wait_return','wait_recruit','wait_draw','fail','quantity'))
CTX=GenerationContext(P+'fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=full(role);r=h.registry if host else defaults()
    if not host:
        for cid in native.EXISTING:
            card=h.registry.card(cid)
            if cid not in r.cards:
                for bid in(card.on_play,card.battlecry,card.deathrattle):
                    if bid is not None:r.register_behavior(bid,h.registry.behavior(bid))
                r.register_card(card)
            if cid not in r.pool_cards:r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_zone_token_draw(r)
    meta=metadata(collectible=False,tribes=())
    r.register_behavior(DONOR,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(SMALL),),SummonCause.capture(c)),))
    r.register_behavior(DONOR+'.cry',lambda c:(GainArmor(c.player_id,50),))
    for cid,cost,atk,hp,kw in((A,2,2,6,{}),(SMALL,1,1,2,{}),(HIGH,8,8,15,{}),
            (DONOR,2,3,4,dict(battlecry=DONOR+'.cry',deathrattle=DONOR)),
            (SAME_A,2,2,6,{}),(SAME_B,4,4,9,{}),(SAME_SLEEP,1,1,2,dict(dormant_turns=2))):
        name='同名测试随从'if cid in(SAME_A,SAME_B,SAME_SLEEP)else cid
        r.register_card(CardDefinition(cid,name,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta,**kw));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def draw(c):
        from hs_sim.engine.effects import Draw
        return(Draw(c.player_id,1,c.source_id),)
    def move(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==BOT)
        return(MoveCard(CardReference.capture(e),c.player_id,Zone.DECK,position='top',source_id=c.source_id),)
    bodies={NOOP:lambda c:(),DRAW:draw,KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        KILL_FILL:lambda c:(AddToHand(c.player_id,NOOP,c.source_id),Destroy(c.target_id,c.source_id)),
        EARLY_FILL:lambda c:(AddToHand(c.player_id,NOOP,c.source_id),TriggerDeathrattles(c.target_id,c.source_id)),
        HUSH:lambda c:(Silence(c.target_id),),TO_SAME:lambda c:(Transform(c.target_id,SAME_A),),MOVE_BOT:move,
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(A),),SummonCause.capture(c)),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);target=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,KILL_FILL,EARLY_FILL,HUSH,TO_SAME)else None
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=meta));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(SLUDGE,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(SLUDGE,SLUDGE,CardType.SPELL,on_play=NOOP,on_destroyed=SLUDGE,metadata=meta))
    for cid,cost,name in((SPELL8,8,SPELL8),(SPELL3,3,SPELL3),(SPELL0,0,SPELL0),(FAKE_BOMB,5,'炸弹')):
        r.register_card(CardDefinition(cid,name,CardType.SPELL,cost=cost,on_play=NOOP,metadata=meta));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(QUANTITY,QUANTITY,CardType.MINION,health=20,summon_quantities=(SummonQuantitySpec(),),metadata=meta))
    r.register_pool_card(PoolCard.from_definition(r.card(QUANTITY)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K730 deliberate rollback')))
    def wait(c):
        e=c.event;s=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        relevant=(e.kind=='card_added_to_hand'and s is not None and s.card_id==POZZIK or
            e.kind=='card_returned'and target is not None and target.card_id==KANGOR or
            e.kind=='minion_summoned'and target is not None and target.card_id==A and
                any(c.state.entities[i].card_id==MAXIMA for i in c.state.players[1].board)or
            e.kind=='card_drawn'and s is not None and s.card_id in(BALINDA,LYNN))
        if not relevant:return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        sources=[c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id in native.ROOTS]
        if sources:options+=(ChoiceOption('remove','Destroy original source',(Destroy(sources[0].id,c.source_id),)),)
        if sources:options+=(ChoiceOption('return','Return original source',(ReturnToHand(sources[0].id),)),)
        if e.kind=='minion_summoned'and target is not None:
            options+=(ChoiceOption('bounce','Bounce original recruit',(ReturnToHand(target.id),)),)
        if e.kind=='card_drawn'and target is not None and target.zone==Zone.HAND:
            options+=(ChoiceOption('discount','Discount original draw',(ModifyStoredCost(CardReference.capture(target),CostSpec(set_to=1),c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    for cid,event in((WAIT_GIFT,'card_added_to_hand'),(WAIT_RETURN,'card_returned'),(WAIT_RECRUIT,'minion_summoned'),(WAIT_DRAW,'card_drawn')):
        r.register_behavior(cid,wait);declarations={'triggers':(TriggerSpec(event,cid),)}if cid==WAIT_RECRUIT else{'limited_triggers':(LimitedTriggerSpec(event,cid),)}
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=meta,**declarations))
    r.validate();return r,h.context if host else CTX


class ZoneTokenDrawTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,host=False,watch=None):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*8 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*8 if enemy_deck is None else enemy_deck,
            mana=40,max_mana=40,mana_cap=40,armor=500)),seed=730,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,80);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)

    def test_complete_twenty_one_rows_thirty_six_primary_faces_and_full_name_predicate(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),36);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),21)
        self.assertEqual(d['minion_name_identity_count'],8145);self.assertIn('CS2_101t',d['complete_fixed_CN_minion_names'])
        for cid in native.ROOTS+native.DEPENDENCIES+native.EXISTING:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_ten_current_host_real_paid_entries_and_six_real_children(self):
        for cid in native.ROOTS+native.DEPENDENCIES:
            g=self.game((cid,),host=True);sid=self.play(g,cid);self.finish(g);self.assertTrue(g.state.play_history[0].completed)
            self.assertEqual(g.state.play_history[0].source_id,sid)

    def test_Lynn_real_death_draws_then_discards_then_destroys_two_for_both_players(self):
        g=self.game((KILL,),board=(LYNN,));self.play(g,KILL,self.unit(g,LYNN).id)
        self.assertEqual([len(g.state.players[p].hand)for p in(1,2)],[0,0]);self.assertEqual([len(g.state.players[p].deck)for p in(1,2)],[4,4])
        self.assertEqual(len(g.state.discard_history),4);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(sum(e.kind=='card_destroyed_in_deck'for e in g.events),4);self.portable(g)

    def test_Lynn_empty_decks_use_only_two_actual_fatigue_draws_per_player(self):
        g=self.game((KILL,),board=(LYNN,),deck=(),enemy_deck=());self.play(g,KILL,self.unit(g,LYNN).id)
        self.assertEqual([self.hero(g,p).armor for p in(1,2)],[497,497]);self.assertEqual(len(g.state.draw_history),4);self.assertFalse(g.state.discard_history)

    def test_Lynn_draw_casts_are_real_and_complete_before_discard_stage(self):
        g=self.game((KILL,),board=(LYNN,),deck=(CANDLE,BOMB,A,A,A,A));self.play(g,KILL,self.unit(g,LYNN).id)
        self.assertEqual([r.card_id for r in g.state.cast_history],[KILL,CANDLE,BOMB]);self.assertIn(WAX,self.faces(g,1,'board'))
        self.assertEqual(self.hero(g).armor,495);self.assertEqual(len(g.state.players[1].hand),0);self.portable(g)

    def test_Lynn_original_draw_wait_restore_keeps_later_discard_destruction(self):
        g=self.game((KILL,),board=(LYNN,),watch=WAIT_DRAW);self.play(g,KILL,self.unit(g,LYNN).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g);self.finish(g)
        self.assertEqual(len(g.state.discard_history),4);self.assertEqual([len(g.state.players[p].deck)for p in(1,2)],[4,4]);self.portable(g)

    def test_Flik_destroys_same_name_different_ID_stats_in_both_boards_hands_and_decks(self):
        g=self.game((FLIK,SAME_B),board=(SAME_A,A),enemy=(SAME_B,),enemy_hand=(SAME_A,),deck=(SAME_A,A),enemy_deck=(SAME_B,A))
        original=[e.id for e in g.state.entities.values()if e.card_id in(SAME_A,SAME_B)];self.play(g,FLIK,self.unit(g,SAME_B,2).id)
        for i in original:self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history),2);self.assertFalse(g.state.discard_history);self.assertEqual(self.unit(g,A).health,6);self.portable(g)

    def test_Flik_uses_current_transformed_name_instead_of_original_card_identity(self):
        g=self.game((TO_SAME,FLIK),board=(A,),enemy=(SAME_B,));aid=self.unit(g,A).id;self.play(g,TO_SAME,aid)
        self.play(g,FLIK,self.unit(g,SAME_B,2).id);self.assertEqual(g.state.entities[aid].zone,Zone.GRAVEYARD)

    def test_Flik_other_Flik_target_also_destroys_the_original_source(self):
        g=self.game((FLIK,),enemy=(FLIK,));source=self.play(g,FLIK,self.unit(g,FLIK,2).id)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),2);self.portable(g)

    def test_Flik_dormant_same_name_is_not_an_active_board_copy(self):
        g=self.game((FLIK,),enemy=(SAME_A,SAME_SLEEP));sleep=self.unit(g,SAME_SLEEP,2).id;self.play(g,FLIK,self.unit(g,SAME_A,2).id)
        self.assertEqual(g.state.entities[sleep].zone,Zone.BOARD);self.assertFalse(g.state.entities[sleep].active)

    def test_Tickatus_base_removes_exactly_five_own_original_top_cards(self):
        g=self.game((TICKATUS,));other=tuple(g.state.players[2].deck);old=tuple(g.state.players[1].deck);self.play(g,TICKATUS)
        self.assertEqual(tuple(g.state.players[1].deck),old[5:]);self.assertEqual(tuple(g.state.players[2].deck),other)
        self.assertFalse(g.state.death_history);self.assertFalse(g.state.discard_history);self.portable(g)

    def test_Tickatus_real_higher_paid_card_corrupts_same_entity_and_switches_to_opponent(self):
        g=self.game((HIGH,TICKATUS));source=self.entity(g,TICKATUS).id;self.play(g,HIGH);self.assertEqual(g.state.entities[source].card_id,CORRUPTED)
        own=tuple(g.state.players[1].deck);enemy=tuple(g.state.players[2].deck);self.play(g,CORRUPTED)
        self.assertEqual(tuple(g.state.players[1].deck),own);self.assertEqual(tuple(g.state.players[2].deck),enemy[5:]);self.portable(g)

    def test_Tickatus_local_milling_classification_uses_original_stored_destroyed_body(self):
        g=self.game((TICKATUS,),deck=(SLUDGE,)*3);self.play(g,TICKATUS);self.assertFalse(g.state.players[1].deck)
        self.assertEqual(self.hero(g).armor,503);self.assertFalse(g.state.draw_history);self.assertFalse(g.state.discard_history)

    def test_Kangor_normal_death_swaps_original_hand_body_and_returns_same_source_with_Lifesteal(self):
        g=self.game((KILL,A),board=(KANGOR,));source=self.unit(g,KANGOR).id;incoming=self.entity(g,A).id;self.play(g,KILL,source)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertIn(incoming,g.state.players[1].board)
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[incoming].keywords);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_Kangor_full_hand_and_full_board_early_swap_reserves_both_original_slots(self):
        g=self.game((EARLY_FILL,A)+(NOOP,)*8,board=(KANGOR,)+(SMALL,)*6);source=self.unit(g,KANGOR).id;incoming=self.entity(g,A).id
        self.play(g,EARLY_FILL,source);self.assertEqual((len(g.state.players[1].hand),len(g.state.players[1].board)),(10,7))
        self.assertIn(source,g.state.players[1].hand);self.assertIn(incoming,g.state.players[1].board);self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_Kangor_full_hand_after_normal_death_does_not_burn_returned_original(self):
        g=self.game((KILL_FILL,A)+(NOOP,)*8,board=(KANGOR,));source=self.unit(g,KANGOR).id;self.play(g,KILL_FILL,source)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertIn(source,g.state.players[1].hand);self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_Kangor_empty_hand_keeps_dead_original_and_consumes_no_rng(self):
        g=self.game((KILL,),board=(KANGOR,));source=self.unit(g,KANGOR).id;rng=g.snapshot()['rng_state'];self.play(g,KILL,source)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_Kangor_actual_quantity_extra_copies_receive_Lifesteal_and_outgoing_source_returns_once(self):
        g=self.game((KILL,A),board=(KANGOR,QUANTITY));source=self.unit(g,KANGOR).id;incoming=self.entity(g,A).id;self.play(g,KILL,source)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==A]
        self.assertEqual(len(bodies),2);self.assertIn(incoming,[e.id for e in bodies]);self.assertTrue(all(Keyword.LIFESTEAL in e.keywords for e in bodies))
        self.assertEqual(self.faces(g).count(KANGOR),1);self.assertIn(source,g.state.players[1].hand);self.portable(g)

    def test_Kangor_atomic_return_wait_restores_HAND_partner_and_original_Lifesteal_callback(self):
        g=self.game((KILL,A),board=(KANGOR,),watch=WAIT_RETURN);source=self.unit(g,KANGOR).id;incoming=self.entity(g,A).id;self.play(g,KILL,source)
        self.assertIn(source,g.state.players[1].hand);self.assertIn(incoming,g.state.players[1].board);self.fault(g);g=self.portable(g);self.choose(g);self.finish(g)
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[incoming].keywords);self.portable(g)

    def test_Pozzik_actual_two_original_gifts_are_both_bound_before_first_creation_listener(self):
        g=self.game((POZZIK,KILL),watch=WAIT_GIFT);source=self.play(g,POZZIK);self.assertEqual(self.faces(g,2),[BOT,BOT]);original=tuple(g.state.players[2].hand)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(set(g.state.players[1].board),set(original));self.assertFalse(g.state.players[2].hand);self.portable(g)

    def test_Pozzik_one_available_opponent_slot_remembers_only_one_actual_arrival(self):
        g=self.game((POZZIK,KILL),enemy_hand=(NOOP,)*9);source=self.play(g,POZZIK);bot=self.entity(g,BOT,2).id;self.play(g,KILL,source)
        self.assertEqual([i for i in g.state.players[1].board if g.state.entities[i].card_id==BOT],[bot]);self.assertEqual(len(g.state.players[2].hand),9);self.portable(g)

    def test_Pozzik_full_opponent_hand_burns_both_without_any_false_summon(self):
        g=self.game((POZZIK,KILL),enemy_hand=(NOOP,)*10);source=self.play(g,POZZIK);self.play(g,KILL,source)
        self.assertFalse(g.state.players[1].board);self.assertEqual(sum(e.kind=='card_burned'for e in g.events),2);self.assertEqual(len(g.state.players[2].hand),10)

    def test_Pozzik_played_original_Bot_is_not_stolen_from_board(self):
        g=self.game((POZZIK,KILL));source=self.play(g,POZZIK);original=tuple(g.state.players[2].hand);g.apply(EndTurn(1));self.play(g,BOT,player=2)
        played=g.state.players[2].board[0];g.apply(EndTurn(2));self.play(g,KILL,source)
        self.assertIn(played,g.state.players[2].board);self.assertEqual(set(g.state.players[1].board),set(original)-{played});self.portable(g)

    def test_Pozzik_remembers_the_same_Bot_shuffled_into_opponent_deck(self):
        g=self.game((POZZIK,KILL),enemy_hand=(MOVE_BOT,));source=self.play(g,POZZIK);original=[i for i in g.state.players[2].hand if g.state.entities[i].card_id==BOT]
        g.apply(EndTurn(1));self.play(g,MOVE_BOT,player=2);g.apply(EndTurn(2));self.play(g,KILL,source)
        self.assertTrue(set(original)<=set(g.state.players[1].board));self.assertTrue(all(g.state.entities[i].owner==2 for i in original));self.portable(g)

    def test_Pozzik_source_without_original_Battlecry_does_not_take_unrelated_same_name_Bot(self):
        g=self.game((KILL,),board=(POZZIK,),enemy_hand=(BOT,));bot=self.entity(g,BOT,2).id;self.play(g,KILL,self.unit(g,POZZIK).id)
        self.assertIn(bot,g.state.players[2].hand);self.assertFalse(g.state.players[1].board)

    def test_Pozzik_silence_retires_native_memory_and_actual_Deathrattle(self):
        g=self.game((POZZIK,HUSH,KILL));source=self.play(g,POZZIK);self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertEqual(self.faces(g,2),[BOT,BOT]);self.assertFalse(g.state.players[1].board);self.portable(g)

    def test_Waxadred_real_death_shuffles_Candle_and_draw_CAST_summons_fresh_printed_source(self):
        g=self.game((KILL,DRAW),board=(WAX,),deck=());original=self.unit(g,WAX).id;self.play(g,KILL,original)
        self.assertEqual(self.faces(g,1,'deck'),[CANDLE]);self.assertEqual(len(g.state.deck_shuffle_history),1);self.play(g,DRAW)
        fresh=self.unit(g,WAX);self.assertNotEqual(fresh.id,original);self.assertEqual((fresh.attack,fresh.health),(7,5));self.assertEqual(self.hero(g).armor,499)
        self.assertEqual([r.outcome for r in g.state.draw_history],['cast','fatigue']);self.portable(g)

    def test_Waxadred_Candle_at_full_board_still_completes_actual_replacement_draw(self):
        g=self.game((KILL,SUMMON,DRAW),board=(WAX,)+(A,)*6,deck=());source=self.unit(g,WAX).id;self.play(g,KILL,source);self.play(g,SUMMON);self.play(g,DRAW)
        self.assertNotIn(WAX,self.faces(g,1,'board'));self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.hero(g).armor,499);self.portable(g)

    def test_Mankrik_real_Wife_draw_CAST_summons_exact_three_seven_and_attacks_enemy_hero(self):
        g=self.game((MANKRIK,DRAW),deck=());self.play(g,MANKRIK);self.assertEqual(self.faces(g,1,'deck'),[WIFE]);self.play(g,DRAW)
        body=self.unit(g,RAGE);self.assertEqual((body.attack,body.health),(3,7));self.assertEqual(self.hero(g,2).armor,497)
        self.assertEqual(len(g.state.character_attack_history),1);self.assertEqual(g.state.character_attack_history[0].declaration.source_id,body.id);self.portable(g)

    def test_real_Bomb_draw_CAST_damages_actual_caster_and_replacement_draw_is_not_fake_hand_play(self):
        g=self.game((DRAW,),deck=(BOMB,A));self.play(g,DRAW);self.assertEqual(self.hero(g).armor,495);self.assertEqual(self.hero(g,2).armor,500)
        self.assertEqual(self.faces(g),[A]);self.assertEqual([r.card_id for r in g.state.cast_history],[DRAW,BOMB]);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_Blastmaster_counts_only_exact_physical_opponent_Bombs_and_reuses_existing_Boom_Bots(self):
        g=self.game((BOOM,BOMB),deck=(BOMB,)*3,enemy_deck=(BOMB,FAKE_BOMB));self.play(g,BOOM)
        bots=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==BOOMBOT]
        self.assertEqual(len(bots),2);self.assertTrue(all((e.attack,e.health)==(1,1)for e in bots));self.portable(g)

    def test_Blastmaster_complete_count_still_uses_ordinary_board_capacity(self):
        g=self.game((BOOM,),enemy_deck=(BOMB,)*5);self.play(g,BOOM);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(self.faces(g,1,'board').count(BOOMBOT),6)

    def test_Blastmaster_actual_Boom_Bot_death_executes_original_random_enemy_damage(self):
        g=self.game((BOOM,KILL),enemy_deck=(BOMB,));self.play(g,BOOM);self.play(g,KILL,self.unit(g,BOOMBOT).id)
        self.assertIn(self.hero(g,2).armor,range(496,500));self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_Maxima_recruits_original_without_Battlecry_attacks_then_dies_and_runs_real_Deathrattle(self):
        g=self.game((MAXIMA,),deck=(DONOR,NOOP));original=self.entity(g,DONOR,1,'deck').id;self.play(g,MAXIMA)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertEqual(self.hero(g,2).armor,497);self.assertEqual(self.hero(g).armor,500)
        self.assertIn(SMALL,self.faces(g,1,'board'));self.assertEqual(len(g.state.character_attack_history),1);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_Maxima_full_board_keeps_original_deck_and_rng_without_an_attempt(self):
        g=self.game((MAXIMA,),board=(A,)*6,deck=(DONOR,));deck=tuple(g.state.players[1].deck);rng=g.snapshot()['rng_state'];self.play(g,MAXIMA)
        self.assertEqual(tuple(g.state.players[1].deck),deck);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.character_attack_history)

    def test_Maxima_original_recruit_wait_restore_and_bounce_do_not_attack_or_destroy_reentered_card(self):
        g=self.game((MAXIMA,),deck=(A,),watch=WAIT_RECRUIT);original=self.entity(g,A,1,'deck').id;self.play(g,MAXIMA)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'bounce');self.finish(g)
        self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.assertEqual(self.hero(g,2).armor,500);self.assertFalse(g.state.character_attack_history);self.portable(g)

    def test_Balinda_two_actual_original_spell_slots_exchange_current_cost_with_attack_and_health(self):
        g=self.game((BALINDA,),deck=(SPELL8,SPELL3,A));self.play(g,BALINDA);rows=g.state.draw_history
        expected=[{SPELL8:8,SPELL3:3}[r.card_id]for r in rows];self.assertEqual((self.unit(g,BALINDA).attack,self.unit(g,BALINDA).health),tuple(expected))
        self.assertEqual([g.state.entities[r.entity_id].cost for r in rows],[5,5]);self.assertEqual(self.faces(g,1,'deck'),[A]);self.portable(g)

    def test_Balinda_only_one_actual_spell_changes_only_attack_and_never_fatigues_for_missing_match(self):
        g=self.game((BALINDA,),deck=(SPELL8,A));self.play(g,BALINDA);self.assertEqual((self.unit(g,BALINDA).attack,self.unit(g,BALINDA).health),(8,5))
        self.assertEqual(self.entity(g,SPELL8).cost,5);self.assertEqual(len(g.state.draw_history),1)

    def test_Balinda_original_draw_wait_uses_actual_current_hand_quote_after_discount(self):
        g=self.game((BALINDA,),deck=(SPELL8,SPELL3),watch=WAIT_DRAW);self.play(g,BALINDA);self.fault(g);g=self.portable(g);self.choose(g,'discount');self.finish(g)
        self.assertEqual(self.unit(g,BALINDA).attack,1);self.assertEqual([g.state.entities[r.entity_id].cost for r in g.state.draw_history],[5,5]);self.portable(g)

    def test_Balinda_burned_original_keeps_frozen_price_and_never_modifies_an_unrelated_hand_card(self):
        g=self.game((BALINDA,)+(NOOP,)*9,deck=(SPELL8,SPELL3));self.play(g,BALINDA);rows=g.state.draw_history
        self.assertEqual([r.outcome for r in rows],['hand','burned']);expected=[{SPELL8:8,SPELL3:3}[r.card_id]for r in rows]
        self.assertEqual((self.unit(g,BALINDA).attack,self.unit(g,BALINDA).health),tuple(expected));self.assertEqual(self.entity(g,NOOP).cost,0);self.portable(g)

    def test_Balinda_source_return_during_draw_still_completes_draws_without_rebinding_swaps(self):
        g=self.game((BALINDA,),deck=(SPELL8,SPELL3),watch=WAIT_DRAW);self.play(g,BALINDA);g=self.portable(g);self.choose(g,'return');self.finish(g)
        self.assertEqual(self.entity(g,SPELL8).cost,8);self.assertEqual(self.entity(g,SPELL3).cost,3);self.assertIn(BALINDA,self.faces(g));self.portable(g)

    def test_Balinda_draw_cast_root_does_not_swap_replacement_child_cost(self):
        g=self.game((BALINDA,),deck=(CANDLE,));self.play(g,BALINDA)
        self.assertEqual([r.card_id for r in g.state.draw_history],[CANDLE,None]);self.assertIn(WAX,self.faces(g,1,'board'))
        self.assertEqual((self.unit(g,BALINDA).attack,self.unit(g,BALINDA).health),(5,5));self.portable(g)

    def test_Balinda_zero_second_spell_cost_uses_ordinary_stat_death(self):
        g=self.game((BALINDA,),deck=(SPELL0,SPELL0));source=self.play(g,BALINDA)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),1)
        self.assertTrue(all(g.state.entities[r.entity_id].cost==5 for r in g.state.draw_history));self.portable(g)

    def test_new_private_native_memory_and_original_draw_material_never_enter_player_DTO(self):
        g=self.game((POZZIK,KILL),watch=WAIT_GIFT);self.play(g,POZZIK);self.portable(g)
        import json
        for player in(1,2):
            text=json.dumps(g.for_player(player).observe())
            for key in('GiveRememberedHandMinions','hand_entry_ids','deck_ids','source_spell_cost_stats','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',text)
