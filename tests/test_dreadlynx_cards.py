"""Real Curious Dreadlynx uses the shared numeric summon/quantity pipeline."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.dreadlynx_cards import CARD, TOKEN, load_batch, register_dreadlynx_cards
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, IllegalAction, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.card_creation import CreatedMinionStats
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (AuraSpec, BattlecryRepeatSpec, CardClass, CardMetadata, Rarity,
    SummonQuantitySpec, SummonStats)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools.card_batch import canonical, check_face

P='fixture.dreadlynx.'
PLAIN,DOUBLE,REPEAT,AURA,WATCH,SEED,ZERO,SUMMON,CLEAR=(P+x for x in
    ('plain','double','repeat','aura','watch','seed','zero','summon','clear'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_dreadlynx_cards(r)
    for cid,extra in((PLAIN,{}),(DOUBLE,dict(summon_quantities=(SummonQuantitySpec(2,(CardType.MINION,)),))),
            (REPEAT,dict(battlecry_repeats=(BattlecryRepeatSpec(),))),
            (AURA,dict(auras=(AuraSpec(attack=3,health=2),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=3,health=12,metadata=META,**extra))
    def fail(c):raise ResolutionError('Dreadlynx deliberate failure')
    r.register_behavior(P+'fail',fail)
    operations={
        SEED:lambda c:(AddToHand(c.player_id,CARD,c.source_id,
            minion_stats=CreatedMinionStats(set_to=SummonStats(8,3))),),
        ZERO:lambda c:(AddToHand(c.player_id,CARD,c.source_id,
            minion_stats=CreatedMinionStats(set_to=SummonStats(0,7))),),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),),
        CLEAR:lambda c:(Silence(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==TOKEN)),),
    }
    for cid,body in operations.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    if mode:
        def watch(c):
            if c.state.entities[c.event.target_id].card_id!=TOKEN:return()
            source=next((e for e in c.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD),None)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='buff_source':return(Buff(source.id,10,10,c.source_id),)if source else()
            if mode=='kill_source':return(Destroy(source.id,c.source_id),)if source else()
            if mode=='damage_source':return(Damage(source.id,2,c.source_id),)if source else()
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
                ChoiceOption('buff','Buff source',(Buff(source.id,7,9,c.source_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec('minion_summoned',P+'watch'),)))
    return r


class DreadlynxCardTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(CARD,),board=(),enemy=(),seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_06',hand=hand,board=((WATCH,)if mode else())+board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',board=enemy,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=367),fixture(mode))
    def play(self,g,cid=CARD):
        i=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,i));return i
    def tokens(self,g):return[e for e in g.state.entities.values()if e.card_id==TOKEN and e.zone==Zone.BOARD]
    def stats(self,g):return[(e.attack,e.health)for e in self.tokens(g)]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original material/quantity and source attribution must restore')
        return Game.from_snapshot(s,r)

    def test_two_full_raw_records_and_all_four_complete_primary_faces(self):
        d=load_batch();rows={x['record']['id']:x for x in d['cards']+d['dependencies']}
        self.assertEqual(set(rows),{CARD,TOKEN});self.assertEqual(len(d['official_observations']),4)
        for cid,row in rows.items():self.assertEqual(canonical(row['record']),row['record_sha256'])
        for o in d['official_observations']:
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations']if o['card_id']==CARD else None)
        a,b=fixture().card(CARD),fixture().card(TOKEN)
        self.assertEqual((a.cost,a.attack,a.health,a.metadata.classes,a.metadata.rarity),(5,2,5,(CardClass.DRUID,),Rarity.EPIC))
        self.assertIn(Keyword.TAUNT,a.keywords);self.assertIn(Keyword.RUSH,b.keywords)
        self.assertEqual((b.cost,b.attack,b.health,b.metadata.collectible),(5,5,2,False))

    def test_both_exact_live_slots_must_be_explicit_and_other_replacements_reject(self):
        d=load_batch();raw=d['cards'][0]['record']
        for o in d['official_observations']:
            if o['card_id']!=CARD:continue
            for norm in(None,{}, {'{0}':''},{'{1}':''},{'{0}':'0','{1}':'0'},{'{0}':'','{1}':'','@':''}):
                with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],norm)

    def test_changed_source_or_primary_rule_numbers_cannot_borrow_display_exception(self):
        d=load_batch();raw=d['cards'][0]['record']
        for o in d['official_observations']:
            if o['card_id']!=CARD:continue
            for key,value in(('id','other'),('cost',6),('health',7),('text',raw['text']+'抽一张牌。')):
                changed=deepcopy(raw);changed[key]=value
                with self.assertRaises(ValueError):check_face(changed,o['face'],o['locale'],d['display_normalizations'])
            for key,value in(('text',o['face']['text']+' Draw a card.'),('manaCost',6),('attack',7),('health',9)):
                face=deepcopy(o['face']);face[key]=value
                with self.assertRaises(ValueError):check_face(raw,face,o['locale'],d['display_normalizations'])

    def test_real_five_mana_battlecry_creates_rush_five_two_beast_with_original_source(self):
        g=self.game();source=self.play(g);self.assertEqual(self.stats(g),[(5,2)])
        self.assertEqual(g.state.players[1].mana,5);e=self.tokens(g)[0]
        self.assertEqual((e.owner,e.controller),(1,1))
        root=g.state.card_summon_history[-1];self.assertEqual(root.request.cause.source.entity_id,source)
        self.assertEqual(root.request.materials[0].stats,SummonStats(5,2));self.portable(g)

    def test_current_created_hand_stats_are_reversed_instead_of_printed_defaults(self):
        g=self.game(hand=(SEED,));self.play(g,SEED);source=self.play(g)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,3))
        self.assertEqual(self.stats(g),[(3,8)]);self.portable(g)

    def test_source_current_aura_is_read_then_recipient_gets_its_own_normal_aura(self):
        g=self.game(board=(AURA,));source=self.play(g)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,7))
        self.assertEqual(self.stats(g),[(10,7)]);self.portable(g)

    def test_quantity_extras_reuse_the_same_accepted_reversed_material(self):
        g=self.game(board=(DOUBLE,));self.play(g);self.assertEqual(self.stats(g),[(5,2),(5,2)])
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_first_entry_source_growth_does_not_rewrite_already_accepted_extra(self):
        g=self.game('buff_source',board=(DOUBLE,));source=self.play(g)
        self.assertEqual(self.stats(g),[(5,2),(5,2)]);self.assertEqual(g.state.entities[source].attack,22);self.portable(g)

    def test_first_entry_source_death_does_not_cancel_already_accepted_extra(self):
        g=self.game('kill_source',board=(DOUBLE,));source=self.play(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.stats(g),[(5,2),(5,2)]);self.portable(g)

    def test_actual_repeated_battlecry_requeries_remaining_health_at_each_original_body(self):
        g=self.game('damage_source',board=(REPEAT,));source=self.play(g)
        self.assertEqual(self.stats(g),[(5,2),(3,2)])
        self.assertEqual((g.state.entities[source].health,g.state.entities[source].max_health),(1,5))
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_full_board_keeps_paid_source_and_skips_beast_without_rng(self):
        g=self.game(board=(PLAIN,)*6);rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.stats(g),[]);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_partial_quantity_capacity_delivers_only_one_actual_beast(self):
        g=self.game(board=(DOUBLE,)+(PLAIN,)*4);self.play(g);self.assertEqual(self.stats(g),[(5,2)])
        self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_zero_source_attack_creates_real_zero_health_beast_then_normal_death(self):
        g=self.game(hand=(ZERO,));self.play(g,ZERO);self.play(g);self.assertFalse(self.tokens(g))
        rows=[r for r in g.state.successful_summon_history if r.card_id==TOKEN]
        self.assertEqual([(r.entry_attack,r.entry_health)for r in rows],[(7,0)])
        self.assertEqual(g.state.entities[rows[0].entity_id].zone,Zone.GRAVEYARD);self.portable(g)

    def test_effect_summon_of_source_has_taunt_without_activating_battlecry(self):
        g=self.game(hand=(SUMMON,));self.play(g,SUMMON);self.assertFalse(self.tokens(g));self.portable(g)

    def test_quantity_entry_wait_restore_keeps_frozen_material_after_source_buff(self):
        g=self.game('wait',board=(DOUBLE,));source=self.play(g);self.assertEqual(self.stats(g),[(5,2)])
        other=self.portable(g);self.choose(g,'buff');self.choose(other,'buff');self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual(self.stats(g),[(5,2),(5,2)]);self.assertEqual(g.state.entities[source].attack,9)
        self.portable(g);self.choose(g);self.portable(g)

    def test_failed_choice_keeps_paid_wait_and_entry_failure_rolls_back_whole_play(self):
        g=self.game('wait');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g);self.assertEqual(g.state.players[1].mana,5)
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertTrue(g.snapshot()==before)

    def test_silence_of_variable_beast_restores_its_real_printed_base_stats(self):
        g=self.game(hand=(SEED,CLEAR));self.play(g,SEED);self.play(g);self.assertEqual(self.stats(g),[(3,8)])
        self.play(g,CLEAR);self.assertEqual(self.stats(g),[(5,2)]);self.portable(g)

    def test_actual_rush_allows_minion_attack_and_rejects_same_turn_enemy_hero(self):
        g=self.game(enemy=(PLAIN,));self.play(g);e=self.tokens(g)[0];before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,e.id,g.state.players[2].hero_id))
        self.assertTrue(g.snapshot()==before);g.apply(Attack(1,e.id,g.state.players[2].board[0]));self.portable(g)

    def test_second_seat_player_views_hide_private_creation_recipe_and_work(self):
        g=self.game('wait',seat=2);self.play(g);before=g.snapshot()
        for pid in(1,2):
            text=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in('card_summon_history','accepted_stats','SummonEntryMaterial','minion_stats'):
                self.assertNotIn(key,text)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.portable(g)
