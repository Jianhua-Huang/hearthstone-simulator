"""Physical Fabled families, genuine draw arrivals and native source lifetimes."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p67_cards as cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p67_cards import (LOGOSH, BROLL, VALEERA, GARONA, KING,
    KINGSLAYERS, CANNON, CATACOMBS, MORCHOK, SHIFTER, CANNONEER, ROOTS, PREFIX,
    load_batch, register_simple_followup_p67_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, PlayCard, PlayerSetup,
    Rarity, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, GainArmor, InvokeBehavior,
    ModifyCost, RequestChoice, ReturnToHand, ShuffleIntoDeck, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fabled_decks import expand_fabled_cards
from hs_sim.engine.model import CastWhenDrawnSpec, CostSpec, LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p67.test.'
A, B, BIG, ZERO, LEGEND, LEGEND_SPELL, WATCH, DOUBLE = (TEST+s for s in ('a','b','big','zero','legend','legend_spell','watch','double'))
KILL, NOOP, DRAW, REPLACEMENT, ARMOR, BUFF_COST, SILENCE = (TEST+s for s in ('kill','noop','draw','replacement','armor','buff_cost','silence'))
GIVE_B = TEST+'give_b'
YETI = 'CORE_CS2_182'
CONTEXT = GenerationContext('p67-complete-explicit-fixture', 'experimental')
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def metadata(rarity=Rarity.COMMON):
    return CardMetadata(True, (CardClass.NEUTRAL,), rarity)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None): r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p67_cards(r)
    elif not all(present): raise AssertionError('P67 requires both complete families and the complete assigned scope')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=batch_registry()
    for cid,cost,atk,hp,rarity in ((A,2,2,3,Rarity.COMMON),(B,3,3,4,Rarity.COMMON),
            (BIG,8,8,12,Rarity.COMMON),(ZERO,0,0,4,Rarity.COMMON),(LEGEND,4,4,5,Rarity.LEGENDARY)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=metadata(rarity)))
    def fail(c): raise ResolutionError('P67 deliberate continuation failure')
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
    def cycle_draw(c):
        ref=CardReference.capture(c.state.entities[c.target_id])
        return (MoveCard(ref,c.player_id,Zone.DECK,position='top',source_id=c.source_id), Draw(c.player_id,1,c.source_id))
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'cycle_draw',cycle_draw)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),), NOOP:lambda c:(), DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        REPLACEMENT:lambda c:(), ARMOR:lambda c:(GainArmor(c.player_id,7),),
        BUFF_COST:lambda c:(ModifyCost(c.target_id,CostSpec(set_to=1),c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),), LEGEND_SPELL:lambda c:(),GIVE_B:lambda c:(AddToHand(c.player_id,B,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION if cid==KILL else CardType.SPELL,
            health=1 if cid==KILL else 0,cost=3 if cid==LEGEND_SPELL else 0,
            battlecry=cid if cid==KILL else None,on_play=None if cid==KILL else cid,
            cast_when_drawn=CastWhenDrawnSpec() if cid==REPLACEMENT else None,
            keywords=(Keyword.CASTS_WHEN_DRAWN,) if cid==REPLACEMENT else (),
            targeting=TargetSpec() if cid in (KILL,BUFF_COST,SILENCE) else None,
            metadata=metadata(Rarity.LEGENDARY if cid==LEGEND_SPELL else Rarity.COMMON)))
    r.register_card(CardDefinition(DOUBLE,'Quantity witness',CardType.MINION,health=20,
        summon_quantities=(SummonQuantitySpec(2),),metadata=metadata()))
    if mode:
        event={'entry':'minion_summoned','buff':'stats_changed','draw':'card_drawn',
            'move':'card_moved_to_hand','destroy':'card_destroyed_in_hand'}[mode]
        def eligible(c):
            e=c.state.entities.get(c.event.target_id)
            if e is None:return False
            if mode=='entry':return e.card_id in cards.FIGHTERS
            if mode=='buff':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in cards.FIGHTERS
            if mode=='destroy':return e.card_id==KING
            return c.event.player_id==1
        def wait(c):
            target=c.event.target_id
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode in ('entry','buff'):
                options += [ChoiceOption('kill','Kill original',(Destroy(target,c.source_id),)),
                    ChoiceOption('cycle','Leave and reenter',(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target)))]
            elif mode in ('draw','move'):
                options += [ChoiceOption('cycle','Leave hand and draw again',(InvokeBehavior(TEST+'cycle_draw',c.source_id,1,target),)),
                    ChoiceOption('discount','Change actual current cost',(ModifyCost(target,CostSpec(set_to=1),c.source_id),))]
                king=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==KING),None)
                if king is not None:
                    options.append(ChoiceOption('king_cycle','King leaves and reenters',(ReturnToHand(king),InvokeBehavior(TEST+'reenter',c.source_id,1,king))))
            return (RequestChoice(1,tuple(options),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,'One-use actual checkpoint',CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),),metadata=metadata()))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in ('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP67Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*12,enemy_hand=(),enemy_deck=(YETI,)*12,
            weapon=None,mode=None,hand_cap=None,enemy_armor=0):
        self.config=mode
        if mode:board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=hand,board=board,deck=deck,
            weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40,hand_cap=hand_cap),
            PlayerSetup('HERO_03',hand=enemy_hand,board=enemy,deck=enemy_deck,armor=enemy_armor,mana=40,max_mana=40,mana_cap=40)),
            seed=6767,generation_context=CONTEXT),fixture_registry(mode,'writer',SOURCE_PIN))

    def first(self,g,cid,zone='hand',player=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None,player=1):
        e=self.first(g,cid,player=player)
        g.apply(PlayCard(player,e.id,target_id=target,position=len(g.state.players[player].board)if e.kind==CardType.MINION else None))
        return e.id

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        reader=fixture_registry(self.config,'reader',SOURCE_PIN)
        self.assertIsNot(g.registry,reader);self.assertEqual(g.registry.fingerprint(),reader.fingerprint())
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('rng_state','resolution_frame','behavior_id','hand_entries','draw_history','defining_card_id'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a0_morchok_actual_draw_budget_and_last_partial_discount(self):
        g=self.game((MORCHOK,),deck=(A,B,BIG,YETI));self.play(g,MORCHOK)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[A,B,BIG])
        self.assertEqual([quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount for i in g.state.players[1].hand],[0,0,3])
        self.assertEqual(len(g.state.draw_history),3);self.assertTrue(all(r.completed and r.parent_id is None for r in g.state.draw_history));self.portable(g)

    def test_a1_morchok_draw_replacement_is_original_chain_not_unrelated_draw(self):
        g=self.game((MORCHOK,),deck=(REPLACEMENT,A,BIG));self.play(g,MORCHOK)
        self.assertEqual(len(g.state.draw_history),3)
        root=g.state.draw_history[0];self.assertEqual(root.outcome,'cast');self.assertEqual(root.replacement_id,g.state.draw_history[1].id)
        self.assertEqual(g.state.draw_history[1].parent_id,root.id)
        self.assertEqual([quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount for i in g.state.players[1].hand],[0,0]);self.portable(g)

    def test_a2_blood_fighter_original_hand_movement_native_buff_and_forced_attack(self):
        g=self.game((KILL,BROLL),board=(LOGOSH,));original=self.first(g,BROLL).id
        self.play(g,KILL,self.first(g,LOGOSH,'board').id)
        e=g.state.entities[original];self.assertEqual((e.zone,e.attack,e.health),(Zone.BOARD,12,12))
        self.assertEqual(len(g.state.character_attack_history),1);row=g.state.character_attack_history[0]
        self.assertEqual(row.declaration.source_id,original);self.assertTrue(row.declaration.forced)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,18);self.portable(g)

    def test_a3_two_other_fighters_grant_only_their_own_keyword(self):
        for source,keyword in ((BROLL,Keyword.TAUNT),(VALEERA,Keyword.ELUSIVE)):
            with self.subTest(source=source):
                g=self.game((KILL,LOGOSH),board=(source,));original=self.first(g,LOGOSH).id
                self.play(g,KILL,self.first(g,source,'board').id);e=g.state.entities[original]
                self.assertEqual((e.attack,e.health),(12,12));self.assertIn(keyword,e.keywords)
                self.assertFalse(g.state.character_attack_history);self.portable(g)

    def test_a4_blood_quantity_extras_each_receive_independent_native_followup(self):
        g=self.game((KILL,VALEERA),board=(BROLL,DOUBLE));self.play(g,KILL,self.first(g,BROLL,'board').id)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==VALEERA]
        self.assertEqual(len(bodies),2);self.assertTrue(all((e.attack,e.health)==(12,12)and Keyword.TAUNT in e.keywords for e in bodies))
        root=g.state.card_summon_history[-1];self.assertEqual(root.status,'completed')
        self.assertTrue(all(d.followup_started for d in root.deliveries));self.portable(g)

    def test_a5_blood_waiting_restore_failure_rollback_and_original_reentry_not_adopted(self):
        g=self.game((KILL,LOGOSH),board=(BROLL,),mode='entry');original=self.first(g,LOGOSH).id
        self.play(g,KILL,self.first(g,BROLL,'board').id);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'cycle')
        e=g.state.entities[original];self.assertEqual((e.zone,e.attack,e.health),(Zone.BOARD,7,7))
        self.assertNotIn(Keyword.TAUNT,e.keywords);self.portable(g)

    def test_a6_blood_buff_reaction_cannot_grant_keyword_to_new_residence(self):
        g=self.game((KILL,LOGOSH),board=(VALEERA,),mode='buff');original=self.first(g,LOGOSH).id
        self.play(g,KILL,self.first(g,VALEERA,'board').id);self.portable(g);self.choose(g,'cycle')
        e=g.state.entities[original];self.assertNotIn(Keyword.ELUSIVE,e.keywords);self.assertEqual(e.attack,7);self.portable(g)

    def test_b0_garona_actual_enemy_king_destroyed_without_discard_death_or_armor_loss(self):
        g=self.game((GARONA,),enemy_hand=(KING,KING,A),enemy_armor=7);original=self.first(g,KING,player=2).id
        self.play(g,GARONA);self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,15)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,7)
        self.assertEqual(sum(g.state.entities[i].card_id==KING for i in g.state.players[2].hand),1)
        self.assertFalse(g.state.death_history);self.assertFalse(g.state.discard_history);self.portable(g)

    def test_b1_garona_no_king_and_friendly_king_do_not_activate(self):
        g=self.game((GARONA,KING),enemy_hand=(A,));before=g.snapshot()['rng_state'];self.play(g,GARONA)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.first(g,KING).zone,Zone.HAND);self.portable(g)

    def test_b2_king_actual_draw_then_original_shuffle_no_duplicate_or_battlecry_reentry(self):
        g=self.game((KING,),deck=(A,));king=self.play(g,KING)
        self.assertEqual(g.state.entities[king].zone,Zone.DECK);self.assertEqual(g.state.players[1].deck,[king])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[A])
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(len(g.state.draw_history),1);self.portable(g)

    def test_b3_king_draw_wait_reentry_does_not_shuffle_a_later_residence(self):
        g=self.game((KING,),deck=(A,),mode='draw');king=self.play(g,KING);self.portable(g)
        self.choose(g,'king_cycle');self.assertEqual(g.state.entities[king].zone,Zone.BOARD)
        self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_b4_true_fabled_opening_moves_original_king_once_and_preserves_construction(self):
        self.config=None;r=fixture_registry(None,'writer',SOURCE_PIN)
        first=(GARONA,KING,KINGSLAYERS,YETI,YETI,YETI,YETI,YETI)
        second=(YETI,)*8
        policy=DeckPolicy('p67-opening',CONTEXT.target_id,CONTEXT.mode,tuple(r.cards),deck_size=8,max_copies=8)
        setup=MatchSetup((DeckSpec('HERO_03','HERO_03bp',CardClass.ROGUE,first),
            DeckSpec('HERO_03','HERO_03bp',CardClass.ROGUE,second)),policy,'GAME_005',seed=6767,first_player=1)
        g=Game.from_decks(setup,r)
        kings=[e for e in g.state.entities.values()if e.card_id==KING]
        self.assertEqual(len(kings),1);king=kings[0];self.assertEqual((king.owner,king.controller),(1,2))
        self.assertEqual(tuple(g.state.players[1].original_deck),first);self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g)
        self.assertEqual(expand_fabled_cards((LOGOSH,),r),(LOGOSH,BROLL,VALEERA))
        self.assertEqual(expand_fabled_cards((GARONA,),r),(GARONA,KING,KINGSLAYERS))

    def test_c0_kingslayers_actual_last_durability_attack_both_physical_legendary_kinds(self):
        g=self.game((ARMOR,),weapon=KINGSLAYERS,deck=(A,LEGEND_SPELL),enemy_deck=(B,LEGEND))
        hero=g.state.players[1].hero_id;enemy=g.state.players[2].hero_id
        g.apply(Attack(1,hero,enemy));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[ARMOR,LEGEND_SPELL])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand],[LEGEND]);self.portable(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,hero,enemy))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(len(g.state.draw_history),4);self.portable(g)

    def test_c1_hand_cannon_native_fire_has_no_end_turn_subject_or_clock(self):
        g=self.game(board=(CANNONEER,CANNONEER),weapon=CANNON);hero=g.state.players[1].hero_id;enemy=g.state.players[2].hero_id
        g.apply(Attack(1,hero,enemy));self.assertEqual(g.state.entities[enemy].health,25)
        self.assertEqual(len(g.state.character_attack_history),1);self.assertFalse(g.state.end_turn_history);self.portable(g)

    def test_c2_hand_cannon_silenced_named_bodies_fire_and_enemy_bodies_do_not(self):
        g=self.game((SILENCE,),board=(CANNONEER,),enemy=(CANNONEER,),weapon=CANNON)
        self.play(g,SILENCE,self.first(g,CANNONEER,'board').id)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        shots=[e for e in g.events if e.kind=='damage_dealt'and e.source_id==self.first(g,CANNONEER,'board').id]
        self.assertEqual(len(shots),1);self.portable(g)

    def test_d0_catacombs_private_original_deck_offer_move_and_temporary_expiry(self):
        g=self.game((CATACOMBS,),deck=(A,B,BIG,A,B,CATACOMBS));original=set(g.state.players[1].deck)
        self.play(g,CATACOMBS);q=g.state.pending_choice;self.assertEqual(len(q.options),3)
        self.assertEqual(tuple(o.id for o in q.options),('zone-1','zone-2','zone-3'))
        self.assertTrue(all(o.entity_id is None and o.id.startswith('zone-')and o.card_id!=CATACOMBS for o in q.options))
        public=json.dumps(g.for_player(2).observe());self.assertNotIn('zone-',public);self.portable(g)
        chosen=q.options[0].card_id;self.choose(g,q.options[0].id);e=self.first(g,chosen)
        self.assertIn(e.id,original);self.assertIsNotNone(e.hand_lifetime);self.assertEqual(e.hand_lifetime.expires_turn,g.state.turn)
        self.assertFalse(g.state.draw_history);self.portable(g);g.apply(EndTurn(1));self.assertEqual(g.state.entities[e.id].zone,Zone.GRAVEYARD);self.portable(g)

    def test_d1_catacombs_acquisition_wait_cycle_is_not_adopted_and_failure_rolls_back(self):
        g=self.game((CATACOMBS,),deck=(A,),mode='move');self.play(g,CATACOMBS);self.choose(g,g.state.pending_choice.options[0].id)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'cycle');e=self.first(g,A)
        self.assertIsNone(e.hand_lifetime);self.assertEqual(len(g.state.hand_entries),3);self.portable(g)

    def test_d2_empty_catacombs_and_empty_blood_candidates_do_not_consume_rng(self):
        for cid,board,hand,deck in ((CATACOMBS,(),(CATACOMBS,),(CATACOMBS,)),(KILL,(LOGOSH,),(KILL,A),())):
            g=self.game(hand,board=board,deck=deck);before=g.snapshot()['rng_state']
            self.play(g,cid,self.first(g,LOGOSH,'board').id if cid==KILL else None)
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_e0_morchok_wait_actual_cost_and_stale_original_arrival(self):
        g=self.game((MORCHOK,),deck=(BIG,BIG),mode='draw');self.play(g,MORCHOK);self.portable(g);self.choose(g,'discount')
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(g.state.draw_history[-1].outcome,'fatigue');self.assertEqual([quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount for i in g.state.players[1].hand],[0,0]);self.portable(g)
        g=self.game((MORCHOK,),deck=(A,BIG),mode='draw');self.play(g,MORCHOK);self.choose(g,'cycle')
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(quote_unselected_cost(g.state,g.registry,self.first(g,A)).amount,2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[BIG]);self.portable(g)

    def test_e1_morchok_empty_burn_and_zero_cost_termination_use_native_draws(self):
        g=self.game((MORCHOK,),deck=());self.play(g,MORCHOK)
        self.assertEqual(g.state.draw_history[0].outcome,'fatigue');self.portable(g)
        g=self.game((MORCHOK,),deck=(A,BIG),hand_cap=1);self.play(g,MORCHOK)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned']);self.portable(g)
        g=self.game((MORCHOK,),deck=(ZERO,ZERO));self.play(g,MORCHOK)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','hand','fatigue']);self.portable(g)

    def test_f0_shifter_retains_only_original_native_source_after_multiple_printed_faces(self):
        g=self.game((SHIFTER,),enemy_hand=(A,GIVE_B),enemy_deck=());source=self.first(g,SHIFTER).id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].card_id,SHIFTER)
        g.apply(EndTurn(2));e=g.state.entities[source];self.assertEqual(e.card_id,A)
        bindings=[a for a in e.abilities if a.kind=='defining_hand_source'];self.assertEqual(len(bindings),1)
        self.assertEqual(bindings[0].defining_card_id,SHIFTER);identity=bindings[0].id;self.portable(g)
        g.apply(EndTurn(1));self.play(g,A,player=2);self.play(g,GIVE_B,player=2);g.apply(EndTurn(2));e=g.state.entities[source]
        self.assertEqual(e.card_id,B);self.assertEqual(next(a.id for a in e.abilities if a.kind=='defining_hand_source'),identity);self.portable(g)
        self.play(g,B);self.assertFalse(any(a.kind=='defining_hand_source'for a in g.state.entities[source].abilities));self.portable(g)

    def test_f1_shifter_no_opponent_minion_has_no_rng_and_full_raw_primary_pins_hold(self):
        g=self.game((SHIFTER,),enemy_hand=(NOOP,),deck=(),enemy_deck=());g.apply(EndTurn(1));before=g.snapshot()['rng_state'];g.apply(EndTurn(2))
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.first(g,SHIFTER).card_id,SHIFTER);self.portable(g)
        from tools.card_batch import check_face
        d=load_batch();items={x['record']['id']:x for k in ('cards','dependencies','existing_dependencies','evidence_only')for x in d[k]}
        self.assertEqual(len(d['official_observations']),22);self.assertEqual(len(d['exact_parent_child_links']),8)
        self.assertEqual(len(ROOTS),10);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for obs in d['official_observations']:
            cid=obs['card_id'];check_face(items[cid]['record'],obs['face'],obs['locale'],numeric_normalizations=d['numeric_normalizations'].get(cid))
        self.assertEqual(canonical_digest(asdict(g.registry.card(CANNONEER))),d['existing_dependency_definition_pins'][CANNONEER]['sha256'])


if __name__=='__main__':unittest.main()
