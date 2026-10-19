"""Physical deck-top execution, natural end timing and bounded continuation."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.ohnahra_top_deck_card import CARD, load_batch, register_ohnahra_top_deck_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.deck_card_plays import PlayTopDeckCards
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddCostModifier, ChangeControl, ChoiceOption, Damage,
    Destroy, Draw, GainArmor, InvokeBehavior, RandomDamage, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.zones import CardReference

P='ohnahra.test.'
FILL='CS2_182'
MINION, SPELL, VALUE, TARGET, DRAW, CHOICE, LETHAL, WEAPON, OLD_WEAPON, LOCATION, HERO, BUFF, NEXT, SILENCE, DORMANT, WATCH = (
    P+x for x in ('minion','spell','value','target','draw','choice','lethal','weapon','old_weapon','location','hero','buff','next','silence','dormant','watch'))
DECK_SPELLS=(SPELL,VALUE,TARGET,DRAW,CHOICE,LETHAL)


@lru_cache(maxsize=None)
def registry(role,mode='normal'):
    assert role in ('writer','reader')
    r=build_registry()
    register_ohnahra_top_deck_card(r)
    def fail(c):
        raise ResolutionError('Ohnahra deliberate failure')
    def god(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
    def buff(c):
        result=[]
        for eid in c.state.players[c.player_id].deck:
            e=c.state.entities[eid]
            if e.card_id==MINION:
                result.append(BuffStoredCard(CardReference.capture(e),attack=3,health=4,source_id=c.source_id))
            elif e.card_id==WEAPON:
                result.append(BuffStoredCard(CardReference.capture(e),attack=3,source_id=c.source_id))
            elif e.card_id==VALUE:
                result.append(BuffStoredCard(CardReference.capture(e),source_id=c.source_id,cost=CostSpec(delta=3)))
        return tuple(result)
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'none',lambda c:())
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior(VALUE,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,
        local_cost(c.source)[0],c.source_id,DamageKind.SPELL),))
    r.register_behavior(TARGET,lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
    r.register_behavior(DRAW,lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_behavior(LETHAL,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,50,c.source_id,DamageKind.SPELL),))
    r.register_behavior(CHOICE,lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('one','One',(GainArmor(c.player_id,1),)),
        ChoiceOption('two','Two',(GainArmor(c.player_id,2),))),source_id=c.source_id),))
    r.register_behavior(BUFF,buff)
    r.register_behavior(NEXT,lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1),uses_remaining=1,source_id=c.source_id),))
    r.register_behavior(SILENCE,lambda c:(Silence(god(c)),))
    r.register_behavior(DORMANT,lambda c:(MakeDormant(god(c),1,c.source_id),))
    for cid,body,cost in ((SPELL,P+'none',4),(VALUE,VALUE,4),(TARGET,TARGET,4),(DRAW,DRAW,4),
            (CHOICE,CHOICE,4),(LETHAL,LETHAL,4),(BUFF,BUFF,0),(NEXT,NEXT,0),
            (SILENCE,SILENCE,0),(DORMANT,DORMANT,0)):
        extra={}
        if cid==TARGET:
            from hs_sim.engine import TargetSpec
            extra['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=body,**extra))
    r.register_card(CardDefinition(MINION,MINION,CardType.MINION,cost=20,attack=2,health=4,battlecry=P+'fail'))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=20,attack=1,durability=2,battlecry=P+'fail'))
    r.register_card(CardDefinition(OLD_WEAPON,OLD_WEAPON,CardType.WEAPON,attack=1,durability=2,deathrattle=P+'armor'))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=20,durability=2,on_use=P+'fail'))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,cost=20,health=30,hero_card=True,
        initial_hero_power='HERO_08bp',hero_armor=4,keep_hero_class=True,battlecry=P+'fail'))
    if mode in ('wait','wait_draw','kill','give','fail'):
        def watch(c):
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=(CARD if mode=='wait_draw'else MINION):
                return ()
            if mode=='kill':
                return (Destroy(god(c),c.source_id),)
            if mode=='give':
                return (ChangeControl(god(c),3-c.player_id),)
            if mode=='fail':
                return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            bad=(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id))
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('bad','Fail',bad)),source_id=c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
            triggers=(TriggerSpec('card_drawn'if mode=='wait_draw'else 'minion_summoned',WATCH),)))
    r.validate()
    r.freeze()
    return r


class OhnahraDeckTests(unittest.TestCase):
    def game(self,deck=(MINION,WEAPON,SPELL),*,hand=(),board=(),enemy=(),mode='normal',root=True,capacity=7,weapon=None):
        board=((CARD,)if root else())+board
        if mode in ('wait','wait_draw','kill','give','fail'):
            board=(*board,WATCH)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=board,hand=hand,deck=deck,
            mana=10,max_mana=10,hero_power_card_id='HERO_08bp',weapon_card_id=weapon),
            PlayerSetup('HERO_08',board=enemy,deck=(FILL,)*25,mana=10,max_mana=10,
                hero_power_card_id='HERO_08bp')),seed=254031),registry('writer',mode),Ruleset(max_board=capacity))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid))
        return eid
    def entity(self,g,cid,pid=1,zone='board'):
        return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def hp(self,g,pid):
        return g.state.entities[g.state.players[pid].hero_id].health
    def casts(self,g):
        return [c for c in g.state.cast_history if c.card_id in DECK_SPELLS]
    def end(self,g):
        g.apply(EndTurn(g.state.active_player))
    def portable(self,g,mode='normal'):
        s=g.snapshot()
        self.assertEqual(Game.from_snapshot(s,registry('reader',mode)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),s)
    def choose(self,g,key='ok'):
        p=g.state.pending_choice
        g.apply(SelectChoice(p.player_id,p.id,(key,)))

    def test_a00_complete_real_face_and_assembled_definition_match(self):
        from hs_sim.cards import build_registry as complete
        self.assertEqual(asdict(registry('writer').card(CARD)),asdict(complete().card(CARD)))
        self.assertEqual(load_batch()['cards'][0]['record']['name_en'],"Ohn'ahra")
        self.assertEqual(registry('writer').card(CARD).metadata.classes,('shaman',))
    def test_a01_typed_cause_count_and_old_schema_are_strict(self):
        g=self.game()
        source=self.entity(g,CARD)
        cause=SummonCause(SourceAllocationFact.capture(g.state,source),1,g.state.turn,g.state.action_number)
        good=PlayTopDeckCards(1,source.id,cause)
        good.validate_in_state(g.state,g.registry)
        for count in (True,-1,1.0):
            with self.subTest(count=count),self.assertRaises(ValueError):
                replace(good,count=count)
        with self.assertRaises(ValueError):
            replace(good,player_id=2)
        with self.assertRaises(ValueError):
            replace(cause.source,entity_id=999999)
        foreign=g.state.players[2].hero_id
        bad=replace(good,source_id=foreign,cause=replace(cause,source=replace(cause.source,entity_id=foreign)))
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        with self.assertRaises(ValueError):
            codec.encode(bad)
        s=g.snapshot();s['schema_version']=428
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s,registry('reader'))
    def test_b00_root_uses_real_hand_payment_then_native_owner_end(self):
        g=self.game((SPELL,)*4,hand=(CARD,),root=False)
        self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,1)
        self.end(g)
        self.assertEqual(len(self.casts(g)),3)
        self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len(g.state.players[1].deck),1)
        self.portable(g)
    def test_b01_all_five_types_use_original_entities_without_battlecry_or_hand_staging(self):
        for cid,zone in ((MINION,Zone.BOARD),(SPELL,Zone.GRAVEYARD),(WEAPON,Zone.WEAPON),
                (LOCATION,Zone.BOARD),(HERO,Zone.HERO)):
            with self.subTest(cid=cid):
                g=self.game((cid,));eid=g.state.players[1].deck[0];epoch=g.state.entities[eid].zone_epoch
                self.end(g)
                self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].zone_epoch),(zone,epoch+1))
                self.assertFalse(g.state.players[1].hand)
                self.assertEqual(g.state.players[1].mana,10)
                self.assertFalse(g.state.play_history)
                self.assertFalse([d for d in g.state.draw_history if d.player_id==1])
                self.portable(g)
    def test_b02_stored_material_and_next_card_cost_use_survive_free_execution(self):
        g=self.game((MINION,WEAPON,VALUE),hand=(BUFF,NEXT))
        ids=tuple(g.state.players[1].deck)
        self.play(g,BUFF);self.play(g,NEXT);self.end(g)
        self.assertEqual((g.state.entities[ids[0]].attack,g.state.entities[ids[0]].health),(5,8))
        self.assertEqual(g.state.entities[ids[1]].attack,4)
        self.assertEqual(self.hp(g,2),23)
        self.assertEqual(self.casts(g)[0].source_id,ids[2])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers],[1])
        self.assertEqual(g.state.players[1].mana,10)
        self.portable(g)
    def test_b03_full_board_draws_minion_and_location_then_still_casts_spell(self):
        g=self.game((MINION,LOCATION,SPELL),board=(FILL,)*6)
        ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual(g.state.players[1].hand,list(ids[:2]))
        self.assertEqual([(d.entity_id,d.outcome)for d in g.state.draw_history if d.player_id==1],[(ids[0],'hand'),(ids[1],'hand')])
        self.assertEqual([c.source_id for c in self.casts(g)],[ids[2]])
        self.portable(g)
    def test_b04_full_hand_fallback_burns_original_cards_and_continues(self):
        g=self.game((MINION,LOCATION,SPELL),board=(FILL,)*6,hand=(FILL,)*10)
        ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual([(d.entity_id,d.outcome)for d in g.state.draw_history if d.player_id==1],[(ids[0],'burned'),(ids[1],'burned')])
        self.assertEqual([g.state.entities[eid].zone for eid in ids], [Zone.GRAVEYARD]*3)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.portable(g)
    def test_b05_capacity_is_rechecked_after_the_previous_real_entry(self):
        g=self.game((MINION,LOCATION,SPELL),board=(FILL,)*5)
        ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.entities[ids[0]].zone,Zone.BOARD)
        self.assertEqual(g.state.players[1].hand,[ids[1]])
        self.assertEqual([c.source_id for c in self.casts(g)],[ids[2]])
    def test_b06_custom_capacity_and_empty_or_short_decks_use_no_fatigue(self):
        g=self.game((MINION,SPELL),board=(FILL,)*2,capacity=3);self.end(g)
        self.assertEqual(self.entity(g,MINION,zone='hand').zone,Zone.HAND)
        self.assertEqual(len(g.state.players[1].board),3)
        for n in (0,2):
            with self.subTest(n=n):
                g=self.game((SPELL,)*n);before=g.snapshot()['rng_state'];self.end(g)
                self.assertEqual(len(self.casts(g)),n)
                self.assertEqual(self.hp(g,1),30)
                self.assertEqual(g.snapshot()['rng_state'],before)
    def test_b07_real_automatic_targets_and_no_target_skip_keep_original_cards(self):
        g=self.game((TARGET,SPELL,SPELL),enemy=(FILL,));first=g.state.players[1].deck[0];self.end(g)
        self.assertEqual(self.entity(g,FILL,2).health,3)
        self.assertEqual(self.casts(g)[0].source_id,first)
        self.portable(g)
        g=self.game((TARGET,SPELL,SPELL));self.end(g)
        self.assertEqual(len(self.casts(g)),3)
        self.assertEqual(self.casts(g)[0].failure,'no_target')
        self.assertFalse(g.state.players[1].deck)
        self.portable(g)
    def test_b08_spell_choices_keep_existing_random_automatic_policy(self):
        g=self.game((CHOICE,SPELL,SPELL));self.end(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertIn(g.state.entities[g.state.players[1].hero_id].armor,(1,2))
        self.assertEqual(len(self.casts(g)),3)
        self.portable(g)
    def test_b09_each_attempt_reads_current_top_after_the_previous_spell_draw(self):
        g=self.game((DRAW,MINION,WEAPON,SPELL,FILL));ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual(g.state.players[1].hand,[ids[1]])
        self.assertEqual(g.state.players[1].weapon_id,ids[2])
        self.assertEqual([c.source_id for c in self.casts(g)],[ids[0],ids[3]])
        self.assertEqual(g.state.players[1].deck,[ids[4]])
        self.portable(g)
    def test_c00_hand_silence_and_dormancy_do_not_produce_owner_end_work(self):
        g=self.game((SPELL,)*3,hand=(CARD,),root=False);self.end(g)
        self.assertFalse(self.casts(g))
        for cid in (SILENCE,DORMANT):
            with self.subTest(cid=cid):
                g=self.game((SPELL,)*3,hand=(cid,));self.play(g,cid);self.end(g)
                self.assertFalse(self.casts(g));self.portable(g)
    def test_c01_opponent_end_does_not_fire_again(self):
        g=self.game((SPELL,)*7);self.end(g);self.end(g)
        self.assertEqual(len(self.casts(g)),3)
    def test_c02_accepted_remaining_attempts_keep_original_owner_after_source_death_or_transfer(self):
        for mode in ('kill','give'):
            with self.subTest(mode=mode):
                g=self.game((MINION,WEAPON,SPELL),mode=mode);eid=self.entity(g,CARD).id;self.end(g)
                self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD if mode=='kill'else Zone.BOARD)
                self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,WEAPON)
                self.assertEqual(len(self.casts(g)),1)
                self.assertEqual(self.casts(g)[0].player_id,1)
                self.portable(g,mode)
    def test_c03_new_ohnahra_does_not_join_an_already_accepted_natural_end(self):
        g=self.game((CARD,SPELL,SPELL,SPELL));self.end(g)
        self.assertEqual(sum(g.state.entities[i].card_id==CARD for i in g.state.players[1].board),2)
        self.assertEqual(len(self.casts(g)),2)
        self.assertEqual(len(g.state.players[1].deck),1)
    def test_c04_real_repeat_source_runs_two_distinct_three_attempt_bodies(self):
        g=self.game((SPELL,)*7,board=('TIME_064',));self.end(g)
        self.assertEqual(len(self.casts(g)),6)
        self.assertEqual(len(g.state.players[1].deck),1)
        self.portable(g)
    def test_c05_replaced_weapon_uses_ordinary_deathrattle_and_hero_keeps_actual_slots(self):
        g=self.game((WEAPON,HERO,SPELL),weapon=OLD_WEAPON)
        old_weapon=g.state.players[1].weapon_id;old_hero=g.state.players[1].hero_id
        ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual(g.state.entities[old_weapon].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[old_hero].zone,Zone.GRAVEYARD)
        self.assertEqual((g.state.players[1].weapon_id,g.state.players[1].hero_id),(ids[0],ids[1]))
        self.assertEqual(g.state.entities[ids[1]].armor,6)
        self.portable(g)
    def test_d00_minion_entry_wait_restores_remaining_deck_operations_once(self):
        g=self.game(mode='wait');self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].deck),2)
        self.portable(g,'wait');other=Game.from_snapshot(g.snapshot(),registry('reader','wait'))
        for x in (g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.casts(g)),1)
    def test_d01_full_board_draw_wait_restores_each_actual_delivery(self):
        g=self.game((MINION,LOCATION,SPELL),board=(FILL,)*5,mode='wait_draw');self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].hand),1)
        self.portable(g,'wait_draw');other=Game.from_snapshot(g.snapshot(),registry('reader','wait_draw'))
        for x in (g,other):
            while x.state.pending_choice is not None:self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(g.state.players[1].hand),2)
        self.assertEqual(len(self.casts(g)),1)
    def test_d02_failed_choice_restores_rng_and_original_remaining_queue(self):
        g=self.game(mode='wait');self.end(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.assertEqual(len(self.casts(g)),1);self.portable(g,'wait')
    def test_d03_late_failure_rolls_back_the_whole_end_including_previous_random_spell(self):
        g=self.game((TARGET,MINION,SPELL),enemy=(FILL,FILL),mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)
    def test_d04_terminal_spell_abandons_remaining_physical_cards(self):
        g=self.game((LETHAL,MINION,WEAPON));ids=tuple(g.state.players[1].deck);self.end(g)
        self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual(g.state.players[1].deck,list(ids[1:]))
        self.assertEqual(len(self.casts(g)),1)
        self.portable(g)
    def test_e00_waiting_player_view_hides_future_deck_and_continuation_material(self):
        g=self.game(mode='wait');self.end(g)
        for pid in (1,2):
            view=json.dumps(g.observe(pid))
            for hidden in (WEAPON,SPELL,'PlayTopDeckCards','SummonCause','SourceAllocationFact'):
                self.assertNotIn(hidden,view)
