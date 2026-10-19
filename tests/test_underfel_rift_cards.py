"""Actual Temporary quest through reward, original investment and finite beasts."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.underfel_rift_cards import BEASTS, OBJECT, PREFIX, REWARD, ROOT, load_batch, register_underfel_rift_cards
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TriggerSpec, UseInteractable, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice, Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import Rarity
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.temporary_cards import CreateTemporaryCard, MakeHandCardTemporary
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'underfel.test.'


@lru_cache(maxsize=1)
def dependencies():
    current = build_registry()
    return tuple(current.card(cid) for cid in BEASTS)


def registry(mode=None):
    r = Registry('underfel-native-tests-v1')
    for card in dependencies():
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    register_underfel_rift_cards(r)
    r.register_card(CardDefinition(P+'hero', 'Hero', CardType.HERO, health=100))
    r.register_card(CardDefinition(P+'unit', 'Unit', CardType.MINION, cost=1, attack=1, health=2))
    r.register_card(CardDefinition(P+'weapon', 'Weapon', CardType.WEAPON, cost=1, attack=1, durability=2))
    def temp(c, ids):
        return tuple(CreateTemporaryCard(c.player_id, cid, c.state.turn, source_id=c.source_id) for cid in ids)
    bodies = {
        'noop': lambda c: (),
        'maker': lambda c: temp(c, (P+'noop',)*6),
        'kinds': lambda c: temp(c, (P+'unit',P+'weapon',P+'transformer')),
        'auto': lambda c: (CastSpell(c.player_id,P+'noop',c.source_id),),
        'mark': lambda c: tuple(MakeHandCardTemporary(CardReference.capture(c.state.entities[i]),
            c.state.turn, source_id=c.source_id) for i in c.state.players[c.player_id].hand),
        'fail': lambda c: (AddToHand(c.player_id,'missing.underfel'),),
        'transform': lambda c: (Transform(c.source_id,P+'unit'),),
    }
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        if name != 'transform':
            r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    r.register_card(CardDefinition(P+'transformer','Transformer',CardType.MINION,health=1,battlecry=P+'transform'))
    if mode:
        def watch(c):
            e=c.event
            if mode == 'counter':
                return (CounterSpell(dict(e.data)['window_id']),) if c.state.entities[e.source_id].card_id==P+'noop' else ()
            if mode in ('wait_first','fail_first'):
                if c.state.entities[e.target_id].card_id not in BEASTS:return ()
                count=sum(c.state.entities[i].card_id in BEASTS for i in c.state.players[c.player_id].board)
                if count!=1:return ()
            if mode == 'fail_first':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        event={'counter':'card_committed','wait_quest':'quest_stage_completed',
            'wait_invest':'interactable_use_started','wait_first':'minion_summoned','fail_first':'minion_summoned'}[mode]
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,
            triggers=(TriggerSpec(event,P+'watch'),)))
    return r


class UnderfelRiftTests(unittest.TestCase):
    def game(self, hand=(ROOT,P+'maker'), *, board=(), other_hand=(), mode=None):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(P+'hero',hand=hand,board=board,deck=(P+'noop',)*10,
            mana=30,max_mana=30,mana_cap=30),PlayerSetup(P+'hero',hand=other_hand,deck=(P+'noop',)*10,
            mana=30,max_mana=30,mana_cap=30)),seed=267),registry(mode))
    def eid(self,g,cid,p=1,zone='hand'):
        return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==cid)
    def play(self,g,cid,p=1):
        eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid));return eid
    def q(self,g,p=1):return g.state.entities[g.state.players[p].quests[0]].quest_progress
    def beast_ids(self,g,p=1):return [i for i in g.state.players[p].board if g.state.entities[i].card_id in BEASTS]
    def obj(self,g,index=0):
        return [i for i in g.state.players[1].board if g.state.entities[i].card_id==OBJECT][index]
    def use(self,g,card=None,index=0):
        card=g.state.players[1].hand[0] if card is None else card
        g.apply(UseInteractable(1,self.obj(g,index),card));return card
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def quest(self,g,count=0):
        self.play(g,ROOT);self.play(g,P+'maker')
        for _ in range(count):self.play(g,P+'noop')
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry(self.mode)
        other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('interactable_history','card_summon_history','hand_lifetime','quote_input',
                        'SETASIDE','resolution_frame','rng_state','existing_definition_pins'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a00_full_records_primary_faces_dependencies_and_inert_body_are_exact(self):
        data=load_batch();r=build_registry()
        rows=sum((data[k]for k in ('cards','dependencies','existing_dependencies','evidence_only')),[])
        self.assertEqual((len(rows),len(data['official_observations'])),(7,12))
        for row in rows:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in data['cards']+data['dependencies']+data['existing_dependencies']:
            expected=metadata_from_record(row['record'])
            if row['record']['id']==OBJECT:expected=replace(expected,rarity=Rarity.LEGENDARY)
            self.assertEqual(r.card(row['record']['id']).metadata,expected)
        self.assertEqual(data['metadata_overrides'],{OBJECT:{'rarity':'legendary'}})
        for cid,pin in data['existing_definition_pins'].items():self.assertEqual(canonical_digest(asdict(r.card(cid))),pin)
        self.assertIsNone(data['dependencies'][1]['record']['attack'])
        self.assertEqual((r.card(ROOT).quest.stages[0].goal,r.card(REWARD).cost),(6,5))
        self.assertEqual((r.card(OBJECT).attack,r.card(OBJECT).health,r.card(OBJECT).corpse_value),(0,1,0))
        self.assertFalse(r.card(OBJECT).hand_playable);self.assertNotIn('TLC_446e',r.cards)

    def test_a01_six_actual_temporary_plays_deliver_reward_then_open_and_use_real_rift(self):
        g=self.game();quest=self.play(g,ROOT);self.assertEqual(g.state.players[1].mana,29)
        self.play(g,P+'maker')
        for n in range(5):self.play(g,P+'noop');self.assertEqual(self.q(g).value,n+1)
        self.assertNotIn(REWARD,[g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.play(g,P+'noop');self.assertEqual(g.state.entities[quest].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[1].quests);reward=self.eid(g,REWARD)
        self.assertIsNone(g.state.entities[reward].hand_lifetime)
        self.play(g,REWARD);self.assertEqual(g.state.players[1].mana,24)
        self.assertFalse(g.state.entities[self.obj(g)].active)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.use(g)
        self.assertEqual(len(self.beast_ids(g)),2);self.portable(g)

    def test_a02_plays_before_activation_are_not_retroactively_counted(self):
        g=self.game();self.play(g,P+'maker');self.play(g,P+'noop');self.play(g,ROOT)
        self.assertEqual(self.q(g).value,0);self.play(g,P+'noop');self.assertEqual(self.q(g).value,1)

    def test_a03_ordinary_card_and_automatic_cast_do_not_count_as_temporary_plays(self):
        g=self.game(hand=(ROOT,P+'noop',P+'auto'));self.play(g,ROOT);self.play(g,P+'noop');self.play(g,P+'auto')
        self.assertEqual(self.q(g).value,0);self.assertEqual(len(g.state.cast_history),4)

    def test_a04_opponent_temporary_plays_do_not_advance_your_quest(self):
        g=self.game(hand=(ROOT,),other_hand=(P+'maker',));self.play(g,ROOT);g.apply(EndTurn(1))
        self.play(g,P+'maker',2);self.play(g,P+'noop',2);self.assertEqual(self.q(g).value,0)

    def test_a05_minion_weapon_and_transformed_body_keep_original_temporary_qualification(self):
        g=self.game(hand=(ROOT,P+'kinds'));self.play(g,ROOT);self.play(g,P+'kinds')
        for n,cid in enumerate((P+'unit',P+'weapon',P+'transformer'),1):
            eid=self.play(g,cid);self.assertEqual(self.q(g).value,n)
            self.assertNotEqual(g.state.entities[eid].zone,Zone.HAND)
            self.assertIsNotNone(g.state.play_history[-1].submitted_cost.quote.quote_input.hand_lifetime)
        self.assertEqual(g.state.entities[eid].card_id,P+'unit')
        self.assertIsNone(g.state.entities[eid].hand_lifetime);self.portable(g)

    def test_a06_grant_to_existing_physical_hand_card_uses_the_same_submission_fact(self):
        g=self.game(hand=(ROOT,P+'mark',P+'noop'));self.play(g,ROOT);eid=self.eid(g,P+'noop')
        self.play(g,P+'mark');self.play(g,P+'noop')
        self.assertEqual(g.state.play_history[-1].source_id,eid);self.assertEqual(self.q(g).value,1)

    def test_a07_countered_temporary_spell_is_still_a_completed_physical_play(self):
        g=self.game(mode='counter');self.quest(g);self.play(g,P+'noop')
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.q(g).value,1)

    def test_a08_temporary_expiry_does_not_fabricate_play_progress(self):
        g=self.game();self.quest(g);g.apply(EndTurn(1))
        self.assertEqual(self.q(g).value,0);self.assertFalse(g.state.players[1].hand)

    def test_b00_real_opener_installs_without_a_minion_summon_and_investment_is_not_discard_or_play(self):
        g=self.game(hand=(REWARD,P+'noop'));self.play(g,REWARD);obj=self.obj(g)
        self.assertFalse(any(e.kind=='minion_summoned'and e.target_id==obj for e in g.events))
        plays=len(g.state.play_history);casts=len(g.state.cast_history);spent=g.state.players[1].mana
        held=self.use(g);self.assertEqual(g.state.entities[held].zone,Zone.SETASIDE)
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history),g.state.players[1].mana),(plays,casts,spent))
        self.assertFalse(g.state.discard_history);self.assertEqual(len(self.beast_ids(g)),2)

    def test_b01_full_three_beast_list_and_original_object_cause_are_sampled_twice(self):
        g=self.game(hand=(REWARD,P+'noop'));self.play(g,REWARD);obj=self.obj(g)
        rng=random.Random();rng.setstate(g._rng.getstate());expected=[rng.choice(BEASTS)for _ in range(2)]
        self.use(g);self.assertEqual([g.state.entities[i].card_id for i in self.beast_ids(g)],expected)
        self.assertEqual(g._rng.getstate(),rng.getstate())
        roots=g.state.card_summon_history;self.assertEqual(len(roots),2)
        for root in roots:
            self.assertEqual((root.request.cause.source.entity_id,root.request.cause.source.card_id),(obj,OBJECT))
            self.assertEqual(tuple(m.card_id for m in root.request.materials),BEASTS)
        self.portable(g)

    def test_b02_two_physical_rifts_have_independent_actual_owner_turn_budgets(self):
        g=self.game(hand=(REWARD,REWARD,P+'noop',P+'noop'));self.play(g,REWARD);self.play(g,REWARD)
        self.use(g,index=0);self.use(g,index=1)
        self.assertEqual(len(self.beast_ids(g)),4)
        self.assertEqual(len({r.entity_id for r in g.state.interactable_history}),2)

    def test_b03_one_or_zero_free_slot_samples_only_each_actual_summon(self):
        for occupants in (5,6):
            with self.subTest(occupants=occupants):
                g=self.game(hand=(REWARD,P+'noop'),board=(P+'unit',)*occupants);self.play(g,REWARD)
                rng=random.Random();rng.setstate(g._rng.getstate())
                if occupants==5:rng.choice(BEASTS)
                self.use(g);self.assertEqual(len(self.beast_ids(g)),6-occupants)
                self.assertEqual(g._rng.getstate(),rng.getstate())
                self.assertEqual(len(g.state.interactable_history),1)

    def test_b04_full_board_opener_uses_existing_failed_install_policy(self):
        g=self.game(hand=(REWARD,),board=(P+'unit',)*7);before=g._rng.getstate();self.play(g,REWARD)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.players[1].mana,25)
        self.assertEqual(g._rng.getstate(),before)
        self.assertTrue(any(e.kind=='interactable_install_skipped'for e in g.events))

    def test_b05_second_use_is_rejected_then_next_actual_owner_start_refreshes(self):
        g=self.game(hand=(REWARD,P+'noop',P+'noop'));self.play(g,REWARD);self.use(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(1));g.apply(EndTurn(2));self.use(g)
        self.assertEqual(len(self.beast_ids(g)),4)
        self.assertNotEqual(g.state.interactable_history[0].owner_turn_id,g.state.interactable_history[1].owner_turn_id)

    def test_c00_public_command_uses_only_owned_handles_and_inert_object_projection(self):
        g=self.game(hand=(REWARD,P+'noop'));self.play(g,REWARD);port=g.for_player(1);response=port.observe()
        own=response['observation']['players'][0];obj=next(x for x in own['board']if x['card_id']==OBJECT)
        self.assertEqual(set(obj),{'ref','card_id','controller','zone','kind','interactable'})
        submitted=port.submit({'revision':response['revision'],'action':{'type':'use_interactable','object':obj['ref'],'card':own['hand'][0]['ref']}})
        self.assertTrue(submitted['accepted'],submitted.get('error'));self.assertEqual(len(self.beast_ids(g)),2)
        self.portable(g)

    def test_d00_completion_wait_preserves_sixth_payment_before_exactly_one_reward(self):
        g=self.game(mode='wait_quest');self.quest(g,5);self.play(g,P+'noop')
        self.assertTrue(self.q(g).completing);self.assertEqual(self.q(g).value,6);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[REWARD])

    def test_d01_investment_wait_is_committed_once_and_does_not_redraw_or_reconsume(self):
        g=self.game(hand=(REWARD,P+'noop'),mode='wait_invest');self.play(g,REWARD);held=self.eid(g,P+'noop')
        rng=g._rng.getstate();self.use(g,held);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[held].zone,Zone.SETASIDE);self.assertEqual(g._rng.getstate(),rng)
        self.assertIsNone(g.state.interactable_history[0].finished_event);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.interactable_history),1)
        self.assertEqual(len(self.beast_ids(g)),2)

    def test_d02_first_summon_wait_keeps_original_random_prefix_and_second_request(self):
        g=self.game(hand=(REWARD,P+'noop'),mode='wait_first');self.play(g,REWARD);self.use(g)
        self.assertEqual(len(self.beast_ids(g)),1);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.beast_ids(g)),2)

    def test_d03_failed_first_summon_reaction_rolls_back_investment_random_and_history(self):
        g=self.game(hand=(REWARD,P+'noop'),mode='fail_first');self.play(g,REWARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),saved)

    def test_e00_real_medivh_triumph_sees_the_inert_rift_as_a_legendary_card(self):
        r=build_registry()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(REWARD,'CATA_308'),deck=('CORE_CS2_182',)*4,
            mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=267),r)
        self.play(g,REWARD);obj=self.obj(g);self.assertEqual(g.state.players[1].mana,25)
        self.play(g,'CATA_308')
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(1,24))
        self.assertEqual(g.state.entities[obj].zone,Zone.BOARD)


if __name__=='__main__':unittest.main()
