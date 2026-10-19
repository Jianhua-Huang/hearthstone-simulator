"""Actual opening deck predicates and native passive price/repeat sources."""
from functools import lru_cache
from dataclasses import replace
import json,unittest

from hs_sim.cards import build_registry
from hs_sim.cards.mugzee_card import ROOT,MUG,ZEE,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,
    EndTurn,Game,IllegalAction,Keyword,MatchSetup,PlayCard,PlayerSetup,Rarity,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.actions import Concede
from hs_sim.engine.costs import capture_generated_quote_fact,quote_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,GainArmor,InvokeBehavior,
    ReplaceHeroPower,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_powers import AddHeroPower,TriggerHeroPower
from hs_sim.engine.model import BattlecryRepeatSpec,CostAuraSpec,CostSpec
from hs_sim.engine.passive_hero_powers import PassiveHeroPowerProfile
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash

P='mugzee.test.'
MINION,FILLER,WEAPON,SPELL=P+'minion',P+'filler',P+'weapon',P+'noop'
BASIC=P+'basic'


@lru_cache(None)
def registry(role='writer',mode='plain'):
    r=build_registry()
    meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def fail(c):raise ResolutionError('deliberate passive power rollback')
    r.register_behavior(P+'fail',fail)
    def body(c):
        effect=GainArmor(c.player_id,1)
        if mode=='wait':return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Gain armor',(effect,)),ChoiceOption('bad','Fail',
                (effect,InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
        if mode=='fail':return(effect,InvokeBehavior(P+'fail',c.source_id,c.player_id))
        if mode=='swap':return(effect,ReplaceHeroPower(c.player_id,BASIC,source_id=c.source_id))
        return(effect,)
    bodies={'body':body,'noop':lambda c:(),
        'basic':lambda c:(GainArmor(c.player_id,1),),
        'mug':lambda c:(ReplaceHeroPower(c.player_id,MUG,source_id=c.source_id),),
        'zee':lambda c:(ReplaceHeroPower(c.player_id,ZEE,source_id=c.source_id),),
        'replace':lambda c:(ReplaceHeroPower(c.player_id,BASIC,source_id=c.source_id),),
        'trigger':lambda c:(TriggerHeroPower(c.player_id,c.source_id),),
        'destroy':lambda c:(Destroy(c.target_id),),
        'summon':lambda c:(Summon(c.player_id,FILLER),)}
    for name,fn in bodies.items():
        r.register_behavior(P+name,fn)
        if name not in('body','basic'):
            r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
                requires_target=name=='destroy',metadata=meta))
    r.register_card(CardDefinition(BASIC,'Scenario active power',CardType.HERO_POWER,cost=2,
        on_use=P+'basic',target_rule='any_entity',metadata=CardMetadata(False,(CardClass.SHAMAN,),None)))
    r.register_card(CardDefinition(P+'hero','Scenario Shaman',CardType.HERO,health=300,
        initial_hero_power=BASIC,metadata=CardMetadata(False,(CardClass.SHAMAN,),None)))
    r.register_card(CardDefinition(MINION,'Battlecry counter',CardType.MINION,cost=4,attack=1,health=2,
        battlecry=P+'body',metadata=meta))
    r.register_card(CardDefinition(FILLER,'Played minion without Battlecry',CardType.MINION,attack=1,health=2,metadata=meta))
    r.register_card(CardDefinition(WEAPON,'Opening weapon fixture',CardType.WEAPON,cost=1,attack=1,durability=2,metadata=meta))
    r.register_card(CardDefinition(P+'blocker','Hero power prohibition fixture',CardType.MINION,health=8,
        keywords=(Keyword.HERO_POWER_SUPPRESSOR,),metadata=meta))
    r.validate();r.freeze();return r


def opening_setup(r,kind='mug',first=1):
    # Explicit eight-card experimental input isolates independent eligibility.
    cards={'mug':(ROOT,)+(SPELL,)*7,'zee':(ROOT,)+(FILLER,)*7,
        'both':(ROOT,)+(WEAPON,)*7,'neither':(ROOT,FILLER)+(SPELL,)*6}[kind]
    own=DeckSpec(P+'hero',BASIC,CardClass.SHAMAN,cards)
    other=DeckSpec(P+'hero',BASIC,CardClass.SHAMAN,(FILLER,)*8)
    policy=DeckPolicy('mugzee-opening-fixture','mugzee-explicit-fixture','experimental',tuple(r.cards),
        deck_size=8,max_copies=20)
    return MatchSetup((own,other),policy,'GAME_005',seed=2921,first_player=first)


class MugZeeTests(unittest.TestCase):
    def game(self,hand=(),*,power=MUG,additional=(),other_power=BASIC,other_hand=(),other_board=(),mode='plain'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(P+'hero',hand=hand,deck=(FILLER,)*30,hero_power_card_id=power,
                additional_hero_power_card_ids=additional,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup(P+'hero',hand=other_hand,board=other_board,deck=(FILLER,)*30,hero_power_card_id=other_power,
                mana=30,max_mana=30,mana_cap=30)),seed=2922),registry('writer',mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        kind=g.registry.card(cid).kind
        g.apply(PlayCard(pid,eid,target,position=len(g.state.players[pid].board)if kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def unlock(self,g):self.cycle(g);self.cycle(g)
    def card(self,g,cid,pid=1):return next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
    def price(self,g,cid,pid=1):return quote_cost(g.state,g.registry,g.state.entities[self.card(g,cid,pid)]).amount
    def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
    def powers(self,g,pid=1):return tuple(g.state.entities[i].card_id for i in g.state.players[pid].hero_power_ids)
    def portable(self,g):
        snap=json.loads(json.dumps(g.snapshot()));r=registry('reader',self.mode)
        restored=Game.from_snapshot(snap,r);self.assertEqual(restored.snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),r).snapshot(),snap);return restored
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})

    def test_a01_full_six_original_sources_and_native_profiles_are_pinned(self):
        d=load_batch();r=registry()
        self.assertEqual((r.card(ROOT).cost,r.card(ROOT).attack,r.card(ROOT).health),(6,6,7))
        self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['evidence_only'])),(1,2,3))
        self.assertTrue(all(r.card(cid).passive_hero_power and r.card(cid).on_use is None for cid in(MUG,ZEE)))
        self.assertEqual(r.passive_hero_power_profiles[MUG].unlock_owner_turn,3)
        self.assertEqual(r.passive_hero_power_profiles[ZEE].battlecry_period,5)

    def test_a02_original_opening_four_independent_qualification_branches(self):
        self.mode='plain';r=registry()
        for kind,expected in(('mug',(MUG,)),('zee',(ZEE,)),('both',(MUG,ZEE)),('neither',(BASIC,))):
            g=Game.from_decks(opening_setup(r,kind),r)
            self.assertEqual(self.powers(g),expected);self.assertEqual(self.powers(g,2),(BASIC,))
            if kind=='both':self.portable(g)

    def test_a03_real_thirty_card_shaman_candidate_deck_gets_mug_before_dealing(self):
        self.mode='plain';r=registry()
        from hs_sim.cards.candidate_generation_catalog import load_batch as load_candidate_catalog
        candidates=set(load_candidate_catalog()['candidate_root_ids'])
        def choose(kind):
            return [cid for cid,c in sorted(r.cards.items())if cid in candidates and c.kind==kind and
                c.metadata.collectible and c.metadata.rarity!=Rarity.LEGENDARY and not c.opening_hooks and
                (CardClass.SHAMAN in c.metadata.classes or CardClass.NEUTRAL in c.metadata.classes)]
        spells=choose(CardType.SPELL);minions=choose(CardType.MINION);self.assertGreaterEqual(min(len(spells),len(minions)),15)
        cards=(ROOT,)+tuple(cid for cid in spells[:14]for _ in range(2))+(spells[14],)
        enemy=tuple(cid for cid in minions[:15]for _ in range(2))
        policy=DeckPolicy('mugzee-thirty-candidates','fixed-cn37-candidates','experimental',tuple(sorted(candidates)))
        setup=MatchSetup((DeckSpec(P+'hero',BASIC,CardClass.SHAMAN,cards),DeckSpec(P+'hero',BASIC,CardClass.SHAMAN,enemy)),policy,'GAME_005',2923,1)
        g=Game.from_decks(setup,r);self.assertEqual(self.powers(g),(MUG,))
        self.assertEqual(len(g.state.players[1].original_deck),30)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(self.powers(g),(MUG,));self.assertEqual(g.state.owner_turn_history[-1].owner_index,1)

    def test_a04_later_normal_root_play_does_not_invent_start_of_game_powers(self):
        g=self.game((ROOT,),power=BASIC);self.play(g,ROOT)
        self.assertEqual(self.powers(g),(BASIC,));self.assertEqual(g.state.players[1].mana,24)

    def test_b01_mug_unlocks_only_at_third_actual_owner_turn_despite_thirty_mana(self):
        g=self.game((MINION,));self.assertEqual(self.price(g,MINION),4)
        self.cycle(g);self.assertEqual(self.price(g,MINION),4)
        self.cycle(g);self.assertEqual(self.price(g,MINION),2)
        self.assertEqual(g.state.players[1].max_mana,30)

    def test_b02_first_actual_minion_gets_two_less_and_spells_do_not_spend_it(self):
        g=self.game((MINION,MINION,SPELL));self.unlock(g);self.play(g,SPELL)
        first=self.play(g,MINION);self.assertEqual(g.state.players[1].mana,28)
        receipt=g.state.play_history[-1].submitted_cost
        self.assertEqual(receipt.quote.amount,2);self.assertEqual(receipt.quote.quote_input.source_id,first)
        self.assertEqual(self.price(g,MINION),4);self.play(g,MINION);self.assertEqual(g.state.players[1].mana,24)

    def test_b03_new_actual_turn_uses_shared_history_instead_of_a_separate_reset_counter(self):
        g=self.game((MINION,MINION));self.unlock(g);self.play(g,MINION)
        self.assertEqual(self.price(g,MINION),4);self.cycle(g);self.assertEqual(self.price(g,MINION),2)

    def test_b04_replacement_stops_aura_and_late_install_does_not_rewind_first_minion(self):
        g=self.game((MINION,MINION,P+'mug',P+'replace'),power=BASIC);self.unlock(g)
        self.play(g,MINION);self.play(g,P+'mug');self.assertEqual(self.price(g,MINION),4)
        self.cycle(g);self.assertEqual(self.price(g,MINION),2)
        self.play(g,P+'replace');self.assertEqual(self.price(g,MINION),4)

    def test_b05_additional_passive_slot_uses_same_quote_and_does_not_discount_opponent(self):
        g=self.game((MINION,),power=BASIC,additional=(MUG,),other_hand=(MINION,));self.unlock(g)
        self.assertEqual(self.price(g,MINION),2);self.assertEqual(self.price(g,MINION,2),4)

    def test_b06_passive_cannot_be_used_manually_or_replayed_as_an_active_payload(self):
        g=self.game((MINION,P+'trigger'));self.unlock(g);power=g.state.players[1].hero_power_id
        self.assertFalse(any(isinstance(a,UseHeroPower)for a in g.legal_actions()));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,entity_id=power))
        self.assertEqual(g.snapshot(),before);self.play(g,P+'trigger')
        self.assertEqual(g.state.hero_power_history[-1].failure,'passive');self.assertEqual(self.price(g,MINION),2)

    def test_b07_shared_prohibition_stops_cost_aura_until_source_is_gone(self):
        g=self.game((MINION,P+'destroy'),other_board=(P+'blocker',));self.unlock(g)
        self.assertEqual(self.price(g,MINION),4);self.play(g,P+'destroy',g.state.players[2].board[0])
        self.assertEqual(self.price(g,MINION),2)

    def test_b08_real_first_payment_wait_restores_and_bad_choice_rolls_back_resume(self):
        g=self.game((MINION,MINION),mode='wait');self.unlock(g);self.play(g,MINION)
        self.assertEqual(g.state.players[1].mana,28);before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.price(g,MINION),4)

    def test_b09_generated_prices_share_the_passive_without_allocating_or_spending_qualification(self):
        g=self.game((MINION,));self.unlock(g);before=g.snapshot()
        for _ in range(3):
            fact=capture_generated_quote_fact(g._state,g.registry,1,MINION)
            self.assertEqual(fact.amount,2)
        self.assertEqual(g.snapshot(),before)
        self.play(g,MINION)
        self.assertEqual(capture_generated_quote_fact(g._state,g.registry,1,MINION).amount,4)

    def test_c01_fifth_minion_double_uses_original_plan_and_only_one_payment(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE)
        for _ in range(4):self.play(g,FILLER)
        source=self.play(g,MINION);self.assertEqual(self.armor(g),2);self.assertEqual(g.state.players[1].mana,26)
        record=g.state.play_history[-1];self.assertEqual(record.source_id,source)
        self.assertEqual(record.battlecry_acceptance.plan.repetitions,2)
        self.assertEqual(len(record.battlecry_acceptance.plan.contributors),1);self.portable(g)

    def test_c02_fifth_without_battlecry_does_not_save_bonus_for_sixth(self):
        g=self.game((FILLER,)*5+(MINION,),power=ZEE)
        for _ in range(5):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.armor(g),1)

    def test_c03_ordinal_continues_across_actual_turns(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE)
        for _ in range(2):self.play(g,FILLER)
        self.cycle(g)
        for _ in range(2):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.armor(g),2)

    def test_c04_spells_and_ordinary_summons_are_not_minion_hand_roots(self):
        g=self.game((SPELL,P+'summon')+(FILLER,)*4+(MINION,),power=ZEE)
        self.play(g,SPELL);self.play(g,P+'summon')
        for _ in range(4):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.armor(g),2)

    def test_c05_players_have_independent_committed_minion_ordinals(self):
        g=self.game((FILLER,)*3+(MINION,MINION),power=ZEE,other_power=ZEE,other_hand=(FILLER,)*4+(MINION,))
        for _ in range(3):self.play(g,FILLER)
        g.apply(EndTurn(1))
        for _ in range(4):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.armor(g,2),2);g.apply(EndTurn(2))
        self.play(g,MINION);self.assertEqual(self.armor(g),1);self.play(g,MINION);self.assertEqual(self.armor(g),3)

    def test_c06_replacing_zee_before_acceptance_stops_repeat(self):
        g=self.game((FILLER,)*4+(P+'replace',MINION),power=ZEE)
        for _ in range(4):self.play(g,FILLER)
        self.play(g,P+'replace');self.play(g,MINION);self.assertEqual(self.armor(g),1)

    def test_c07_already_accepted_double_keeps_second_body_after_skill_replacement(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE,mode='swap')
        for _ in range(4):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.powers(g),(BASIC,));self.assertEqual(self.armor(g),2)

    def test_c08_two_real_body_choices_restore_without_recounting_current_minion(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE,mode='wait')
        for _ in range(4):self.play(g,FILLER)
        self.play(g,MINION);before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for game in(g,restored):
            self.choose(game);self.assertIsNotNone(game.state.pending_choice);self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),2)

    def test_c09_failed_fifth_action_rolls_back_payment_history_and_repetition(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE,mode='fail')
        for _ in range(4):self.play(g,FILLER)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,MINION)
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(g.state.play_history),4)

    def test_c10_actual_two_passive_skill_shape_keeps_zee_additional_slot_functional(self):
        g=self.game((FILLER,)*4+(MINION,),power=MUG,additional=(ZEE,));self.unlock(g)
        for _ in range(4):self.play(g,FILLER)
        self.assertEqual(self.price(g,MINION),4)
        self.play(g,MINION);self.assertEqual(self.armor(g),2)

    def test_d01_shared_prohibition_prevents_passive_battlecry_contribution(self):
        g=self.game((FILLER,)*4+(MINION,),power=ZEE,other_board=(P+'blocker',))
        for _ in range(4):self.play(g,FILLER)
        self.play(g,MINION);self.assertEqual(self.armor(g),1)

    def test_d02_rehashed_missing_or_substituted_native_passive_ability_is_rejected(self):
        g=self.game(power=ZEE);power=g.state.players[1].hero_power_id
        for change in('missing','count','source'):
            snap=g.snapshot();e=snap['state']['entities'][str(power)]
            row=next(a for a in e['abilities']if a['kind']=='battlecry_repeat')
            if change=='missing':e['abilities'].remove(row)
            elif change=='count':row['battlecry_repeat']['repetitions']=3
            else:row['source_id']=g.state.players[1].hero_id
            self.rehash(snap)
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())

    def test_d03_profile_is_frozen_and_native_passives_require_registered_qualifications(self):
        r=registry()
        with self.assertRaises(TypeError):r.passive_hero_power_profiles[MUG]=PassiveHeroPowerProfile(MUG)
        with self.assertRaises(ValueError):PassiveHeroPowerProfile(ZEE,battlecry_period=True)
        from hs_sim.engine import Registry
        standalone=Registry('unknown-passive-policy')
        standalone.register_card(CardDefinition('unknown','Unqualified passive',CardType.HERO_POWER,
            passive_hero_power=True,target_rule='any_entity',battlecry_repeats=(BattlecryRepeatSpec(2,(CardType.MINION,)),)))
        with self.assertRaises(ValueError):standalone.validate()

    def test_d04_player_views_do_not_leak_price_or_repeat_operands_and_terminal_keeps_state(self):
        g=self.game((MINION,));self.unlock(g)
        for pid in(1,2):
            view=json.dumps(g.observe(pid),ensure_ascii=False,default=str)
            for private in('first_play','play_history','contributions','battlecry_period'):
                self.assertNotIn(private,view)
        g.apply(Concede(1));self.assertEqual(g.state.status,'finished');self.portable(g)


if __name__=='__main__':unittest.main()
