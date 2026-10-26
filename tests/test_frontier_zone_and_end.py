"""Actual Frontier zone consumers, source clocks and complete draw replacements."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.frontier_zone_and_end import ROOTS, BLOOD, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, DestroyBatch, Draw, InvokeBehavior, RequestChoice, Silence
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools import card_batch as batch

S='k555.'
WATCH, DRAWER=S+'watch',S+'drawer'
SIX, ZERO, SAFE='EDR_272','CORE_CS2_231','CORE_EX1_169'
CTX=GenerationContext('k555-six-native-frontier-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        old=r.pool(name,fmt.context)
        if name=='constructed.minions':old=replace(old,members=tuple(PoolMember(cid)for cid in (ZERO,SIX)))
        r.register_pool(replace(old,target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','six-native-zone-end-test-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in ROOTS),complete=True))
    def fail(c):raise ResolutionError('k555 late branch failure')
    def wait(c):
        return RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',()),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id)
    def observe(c):
        if mode=='draw_wait' and c.event.kind=='card_drawn' and c.event.player_id==c.player_id:
            drawn=c.state.entities.get(c.event.target_id)
            return (wait(c),)if drawn is not None and drawn.card_id!=BLOOD else ()
        if mode=='summon_wait' and c.event.kind=='minion_summoned':
            roots=tuple(x for x in c.state.card_summon_history if x.request.cause.source.card_id=='ULD_304')
            if len(roots)==1:
                refs=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].hand
                    if c.state.entities[i].card_id==SAFE)
                return (*(ModifyStoredCost(ref,CostSpec(set_to=6),c.source_id)for ref in refs),wait(c))
        return ()
    def grave(c):
        ids=tuple(i for p in c.state.players.values()for i in p.board if c.state.entities[i].card_id!=WATCH)
        return (*(Silence(i)for i in ids),DestroyBatch(ids,c.source_id))
    def price(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=6),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='CORE_CS2_029')
    bodies={'fail':fail,'draw':lambda c:(Draw(c.player_id,1,c.source_id),),'grave':grave,'price':price}
    for name,body in bodies.items():
        r.register_behavior(S+name,body);r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name))
    r.register_behavior(S+'drawer',lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_card(CardDefinition(DRAWER,'Diagnostic dying drawer',CardType.MINION,attack=1,health=1,deathrattle=S+'drawer'))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Consumer observer',CardType.WEAPON,attack=0,durability=30,
        triggers=tuple(TriggerSpec(event,S+'observe')for event in ('card_drawn','minion_summoned'))))
    r.validate();return replace(fmt,context=CTX)


class FrontierZoneEndTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,board=(),deck=(),enemy=(),enemy_deck=(),mode='normal',seed=1):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,max_mana=10,mana=10,
                weapon_card_id=WATCH if mode!='normal'else None),
            PlayerSetup('HERO_08',board=enemy,deck=enemy_deck,max_mana=10,mana=10)),seed=seed,generation_context=CTX),fmt.registry)

    def pick(self,game,cid):self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==cid))

    def test_all_seven_complete_rows_and_fourteen_primary_faces_are_preserved(self):
        data=load_batch();source={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        rows={x['record']['id']:x['record']for key in ('cards','dependencies')for x in data[key]}
        self.assertEqual(len(rows),7)
        for cid,raw in rows.items():self.assertEqual(raw,source[cid])
        for observation in data['official_faces']:
            batch.check_face(rows[observation['card_id']],observation['face'],observation['locale'])
        self.assertEqual(rows['TRL_541']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],rows[BLOOD]['dbf_id'])
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_archmage_really_summons_a_six_cost_only_on_its_controllers_turn_end(self):
        game=self.game(('DAL_553',));source=self.play(game,'DAL_553');game.apply(EndTurn(1))
        bodies=[game.state.entities[i].card_id for i in game.state.players[1].board]
        self.assertEqual(bodies,['DAL_553',SIX])
        self.assertEqual(game.state.card_summon_history[-1].request.cause.source.entity_id,source)
        game.apply(EndTurn(2));self.assertEqual(len(game.state.players[1].board),2);self.portable(game)

    def test_yshaarj_recruits_the_original_deck_minion_without_drawing_the_spell(self):
        game=self.game(('OG_042',),deck=(SAFE,FILLER));original=game.state.players[1].deck[1]
        source=self.play(game,'OG_042');game.apply(EndTurn(1))
        self.assertIn(original,game.state.players[1].board)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].deck],[SAFE])
        root=game.state.recruit_summon_history[-1];self.assertEqual(root.spec.cause.source.entity_id,source)
        self.assertEqual(root.rounds[0].selected.entity_id,original);self.portable(game)

    def test_nzoth_uses_printed_deathrattle_and_separate_same_card_friendly_deaths(self):
        game=self.game((S+'grave','OG_133'),board=('BT_155','BT_155',FILLER),enemy=('CORE_REV_375',))
        self.play(game,S+'grave');self.assertFalse(game.state.players[1].board)
        self.play(game,'OG_133');root=game.state.resurrection_summon_history[-1]
        self.assertEqual((len(root.basis.inventory),len(root.candidates),len(root.picks)),(4,2,2))
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].board],['OG_133','BT_155','BT_155'])
        self.assertEqual(len({p.selected for p in root.picks}),2);self.portable(game)

    def test_deathwing_discards_hand_after_real_death_draw_and_preserves_enemy_location(self):
        game=self.game(('NEW1_030',FILLER),board=(DRAWER,),deck=(SAFE,),enemy=('CORE_REV_990',FILLER))
        old_hand=self.entity(game,FILLER).id;drawn=game.state.players[1].deck[0]
        location=self.entity(game,'CORE_REV_990',player=2,zone='board').id
        source=self.play(game,'NEW1_030')
        self.assertEqual(game.state.players[1].board,[source]);self.assertEqual(game.state.players[2].board,[location])
        self.assertFalse(game.state.players[1].hand)
        discarded={e.target_id for e in game.events if e.kind=='card_discarded'}
        self.assertEqual(discarded,{old_hand,drawn});self.portable(game)

    def test_deathwing_death_draw_wait_restores_before_current_hand_discard(self):
        game=self.game(('NEW1_030',FILLER),board=(DRAWER,),deck=(SAFE,),mode='draw_wait')
        self.play(game,'NEW1_030');self.assertEqual(len(game.state.players[1].hand),2)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertFalse(game.state.players[1].hand);self.portable(game)

    def test_phaoris_captures_original_current_hand_spell_costs_and_does_not_consume_them(self):
        game=self.game((S+'price','ULD_304','CORE_CS2_029',SAFE,FILLER));self.play(game,S+'price')
        kept=set(game.state.players[1].hand)-{self.entity(game,'ULD_304').id}
        self.play(game,'ULD_304')
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].board],['ULD_304',SIX,ZERO])
        self.assertEqual(set(game.state.players[1].hand),kept);self.assertEqual(game.state.players[1].mana,0)

    def test_phaoris_wait_keeps_original_zero_cost_request_when_remaining_spell_reprices(self):
        game=self.game((S+'price','ULD_304','CORE_CS2_029',SAFE),mode='summon_wait')
        self.play(game,S+'price');self.play(game,'ULD_304')
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].board],['ULD_304',SIX,ZERO])
        self.portable(game)

    def test_hakkar_death_shuffles_one_actual_blood_into_each_physical_deck(self):
        game=self.game(('TRL_541',P+'kill'),deck=(FILLER,),enemy_deck=(FILLER,))
        source=self.play(game,'TRL_541');self.play(game,P+'kill',source)
        for player in (1,2):
            deck=[game.state.entities[i]for i in game.state.players[player].deck]
            self.assertEqual(sorted(e.card_id for e in deck),sorted((FILLER,BLOOD)))
            blood=next(e for e in deck if e.card_id==BLOOD);self.assertEqual((blood.owner,blood.controller),(player,player))
        self.portable(game)

    def test_two_drawn_bloods_finish_replacement_fatigue_then_shuffle_four_fresh_copies(self):
        game=self.game((S+'draw',),deck=(BLOOD,BLOOD));self.play(game,S+'draw')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,23)
        self.assertEqual([d.outcome for d in game.state.draw_history],['cast','cast','fatigue'])
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].deck],[BLOOD]*4)
        self.assertEqual(sum(c.card_id==BLOOD for c in game.state.cast_history),2);self.portable(game)

    def test_blood_replacement_wait_saves_original_after_draw_copies_without_early_shuffle(self):
        game=self.game((S+'draw',),deck=(BLOOD,FILLER),mode='draw_wait')
        self.play(game,S+'draw');self.assertFalse(game.state.players[1].deck)
        self.assertEqual(len(game.state.players[1].hand),1)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].deck],[BLOOD]*2)
        self.portable(game)

    def test_manually_played_blood_has_no_after_draw_shuffle(self):
        game=self.game((BLOOD,));self.play(game,BLOOD)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,27)
        self.assertEqual(game.state.players[1].mana,9)
        self.assertFalse(game.state.players[1].deck);self.assertFalse(game.state.draw_history)

    def test_all_six_are_really_discovered_and_played_for_one_through_frontier(self):
        r=fixture().registry
        rows=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=fixture().registry.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual({x.card_id for x in rows},set(ROOTS))
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed=next(n for n in range(100)if cid in sample_candidates(Random(n),rows,3,replacement=False))
                game=self.game(('GDB_857',),seed=seed);self.play(game,'GDB_857');self.pick(game,cid)
                source=self.play(game,cid);self.assertEqual(game.state.entities[source].card_id,cid)
                self.assertEqual((game.state.play_history[-1].cost,game.state.players[1].mana),(1,2))
        self.portable(game)


if __name__=='__main__':unittest.main()
