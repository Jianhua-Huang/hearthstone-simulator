"""Hamuul's real original-deck opening and completed personal casts."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.nature_opening_imbue_card import CARD,PROGRAM,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,EndTurn,
    Game,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SpellSchool,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,ChangeManaCrystals,ChoiceOption,Destroy,GainArmor,
    InvokeBehavior,ModifyCost,RequestChoice,SetManaCap,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.imbue import imbue_count
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import AddToDeck,CardReference,DestroyStoredCard
from hs_sim.targets import canonical_digest

P='ham.opening.test.'
NATURE,ARCANE,UNTYPED,AUTO,WAIT,WATCH=(P+k for k in('nature','arcane','untyped','auto','wait','watch'))
FILLERS=tuple(P+'filler.'+str(i)for i in range(30))


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in('writer','reader')
    r=build_registry();meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def fail(c):raise ResolutionError('Hamuul deliberate choice failure')
    r.register_behavior(P+'fail',fail)
    def wait(c):return (RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
        ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    for cid,school,body in ((NATURE,SpellSchool.NATURE,lambda c:(GainArmor(c.player_id,1),)),
        (ARCANE,SpellSchool.ARCANE,lambda c:(GainArmor(c.player_id,1),)),
        (UNTYPED,None,lambda c:(GainArmor(c.player_id,1),)),
        (AUTO,SpellSchool.NATURE,lambda c:(CastSpell(c.player_id,NATURE,c.source_id),)),
        (WAIT,SpellSchool.NATURE,wait)):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,spell_school=school,on_play=cid,metadata=meta))
    def destroy_original(c):
        program=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==PROGRAM)
        e=c.state.entities[program.source_id]
        return (DestroyStoredCard(CardReference.capture(e),source_id=c.source_id),)if e.zone in(Zone.HAND,Zone.DECK)else(Destroy(e.id,c.source_id),)
    def remove_arcane(c):
        for eid in c.state.opening.original_entities[c.player_id-1]:
            e=c.state.entities[eid]
            if e.card_id==ARCANE and e.zone in(Zone.HAND,Zone.DECK):return (DestroyStoredCard(CardReference.capture(e),source_id=c.source_id),)
        return ()
    r.register_behavior(P+'destroy_original',destroy_original);r.register_behavior(P+'remove_arcane',remove_arcane)
    def seed(c):
        options=[ChoiceOption(key,key,tuple(AddToHand(c.player_id,cid,c.source_id)for _ in range(3)))
            for key,cid in(('nature',NATURE),('arcane',ARCANE),('auto',AUTO),('wait',WAIT))]
        options.extend((ChoiceOption('none','No effect'),
            ChoiceOption('mana','Test mana',(SetManaCap(c.player_id,20),ChangeManaCrystals(c.player_id,20,filled=True))),
            ChoiceOption('watch','Observe',(AddToHand(c.player_id,WATCH,c.source_id),)),
            ChoiceOption('destroy','Original source',(InvokeBehavior(P+'destroy_original',c.source_id,c.player_id),)),
            ChoiceOption('add_arcane','Change current deck',(AddToDeck(c.player_id,ARCANE,source_id=c.source_id),)),
            ChoiceOption('remove_arcane','Remove current arcane',(InvokeBehavior(P+'remove_arcane',c.source_id,c.player_id),)),
            ChoiceOption('power_cost','Current power cost',(ModifyCost(c.state.players[c.player_id].hero_power_id,CostSpec(delta=1,card_types=(CardType.HERO_POWER,))),))))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(P+'seed',seed)
    r.register_behavior(P+'watch',lambda c:wait(c)if c.event.player_id==1 else())
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,metadata=replace(meta,collectible=False),
        triggers=(TriggerSpec('imbued',P+'watch'),)))
    r.register_behavior(P+'opening_watch',lambda c:(Summon(c.player_id,WATCH),)if c.player_id==1 else())
    for cid in FILLERS:
        extra=dict(opening_hooks=(OpeningHook('before_deal',P+'opening_watch'),))if mode=='opening_wait'and cid==FILLERS[0]else{}
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=2,on_play=P+'seed',metadata=meta,**extra))
    r.validate();r.freeze();return r


class NatureOpeningImbueTests(unittest.TestCase):
    def opening(self,school='nature',*,mode=None,first=1,include=True,complete=True):
        self.mode=mode;r=registry('writer',mode)
        marker={'nature':NATURE,'arcane':ARCANE,'untyped':UNTYPED}.get(school)
        cards=(FILLERS[0],CARD,*(()if marker is None else(marker,)),*FILLERS[1:29 if marker is None else 28])if include else FILLERS
        self.assertEqual(len(cards),30)
        decks=(DeckSpec('HERO_06','HERO_06bp',CardClass.DRUID,cards),DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,FILLERS))
        policy=DeckPolicy(P+'policy','cn37-synthetic-hamuul','experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=231845,first_player=first),r)
        if complete:self.finish_opening(g)
        return g
    def finish_opening(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice
            self.assertIn('mulligan',str(q.purpose));g.apply(SelectChoice(q.player_id,q.id,()))
    def entity(self,g,cid,zone='hand',pid=None):
        pid=g.state.active_player if pid is None else pid
        return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid):
        p=g.state.active_player;e=self.entity(g,cid);g.apply(PlayCard(p,e.id,position=len(g.state.players[p].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def seed(self,g,key):
        e=next(g.state.entities[i]for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id in FILLERS)
        self.play(g,e.card_id);self.choose(g,key)
    def count(self,g,pid=1):return imbue_count(g.state,pid)
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode);self.assertIsNot(r,g.registry)
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in(1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in('"original_deck"','"cast_history"','"source_allocation"','"resolution_frame"','"rng_state"'):self.assertNotIn(key,wire)
        return other
    def test_a00_complete_real_source_and_two_strict_primary_faces(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),2)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        c=registry('writer').card(CARD);self.assertEqual((c.cost,c.attack,c.health),(5,5,6));self.assertIsNone(c.battlecry)
        self.assertNotIn('EDR_845e1',registry('writer').cards)
    def test_a01_real_original_thirty_card_deck_imbues_once_before_mulligan(self):
        g=self.opening(complete=False);self.assertEqual(self.count(g),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_847p')
        self.assertEqual(len([e for e in g.state.players[1].player_effects if e.spec_id==PROGRAM]),1)
        self.assertFalse(g.state.cast_history);self.assertEqual(len(g.state.players[1].original_deck),30)
        self.finish_opening(g);self.assertEqual(self.count(g),1);self.portable(g)
    def test_a02_non_nature_and_untyped_original_spells_do_not_install_program(self):
        for school in('arcane','untyped'):
            with self.subTest(school=school):
                g=self.opening(school);self.assertEqual(self.count(g),0)
                self.assertFalse([e for e in g.state.players[1].player_effects if e.spec_id==PROGRAM])
                self.seed(g,'nature')
                for _ in range(3):self.play(g,NATURE)
                self.assertEqual(self.count(g),0)
    def test_a03_existing_empty_spell_subset_policy_is_true(self):
        g=self.opening('empty');self.assertEqual(self.count(g),1);self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),2)
    def test_b00_every_third_completed_cast_counts_generated_other_schools(self):
        g=self.opening();power=g.state.players[1].hero_power_id
        for expected,key in((2,'arcane'),(3,'nature')):
            self.seed(g,key);cid=ARCANE if key=='arcane'else NATURE
            for index in range(3):
                self.play(g,cid);self.assertEqual(self.count(g),expected if index==2 else expected-1)
        self.assertEqual(g.state.players[1].hero_power_id,power);self.assertEqual(len(g.state.cast_history),6);self.portable(g)
    def test_b01_generated_nested_casts_count_separate_actual_completions(self):
        g=self.opening();self.seed(g,'auto');self.play(g,AUTO)
        self.assertEqual((len(g.state.cast_history),self.count(g)),(2,1));self.play(g,AUTO)
        self.assertEqual((len(g.state.cast_history),self.count(g)),(4,2))
        self.assertEqual([r.origin for r in g.state.cast_history].count('effect'),2);self.portable(g)
    def test_b02_minion_plays_and_real_hero_power_use_are_not_spells(self):
        g=self.opening();self.seed(g,'mana');p=g.state.players[1]
        before=set(p.board);g.apply(UseHeroPower(1,p.hero_power_id))
        summoned=set(g.state.players[1].board)-before;self.assertEqual(len(summoned),1)
        body=g.state.entities[summoned.pop()];self.assertEqual((body.attack,body.max_health),(1,1));self.seed(g,'none')
        self.assertFalse(g.state.cast_history);self.assertEqual(self.count(g),1)
    def test_b03_opponent_casts_do_not_advance_owner_program(self):
        g=self.opening();self.seed(g,'nature');g.apply(EndTurn(1));self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),1);self.assertEqual(self.count(g,2),0);g.apply(EndTurn(2))
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),2)
    def test_c00_third_spell_payload_wait_restores_before_imbue_and_choice_failure_rolls_back(self):
        g=self.opening();self.seed(g,'nature');self.play(g,NATURE);self.play(g,NATURE)
        self.seed(g,'wait');self.play(g,WAIT);self.assertEqual(self.count(g),1);self.assertFalse(g.state.cast_history[-1].completed)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.assertEqual(self.count(other),2);self.portable(other)
    def test_c01_imbue_reaction_wait_keeps_completed_cast_and_no_duplicate_reward(self):
        g=self.opening();self.seed(g,'watch');self.play(g,WATCH);self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g),2)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.assertEqual(self.count(other),2);self.portable(other)
    def test_c02_true_opening_imbue_can_wait_before_dealing_and_resume_original_setup(self):
        g=self.opening(mode='opening_wait',complete=False)
        self.assertEqual(g.state.opening.stage,'dealing');self.assertEqual(self.count(g),1)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.finish_opening(other)
        self.assertEqual(self.count(other),1);self.portable(other)
    def test_d00_destroyed_original_source_does_not_remove_accepted_program(self):
        g=self.opening();program=next(e for e in g.state.players[1].player_effects if e.spec_id==PROGRAM)
        self.seed(g,'destroy');self.assertEqual(g.state.entities[program.source_id].zone,Zone.GRAVEYARD)
        self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),2);self.assertEqual(g.state.imbue_history[-1].source_id,program.source_id);self.portable(g)
    def test_d01_current_deck_changes_cannot_rewrite_original_condition(self):
        g=self.opening();self.seed(g,'add_arcane');self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),2)
        g=self.opening('arcane');self.seed(g,'remove_arcane');self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),0)
    def test_d02_playing_generated_hamuul_is_ordinary_minion_without_opening_reward(self):
        self.mode=None;g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=(CARD,NATURE,NATURE,NATURE),mana=10,max_mana=10),PlayerSetup('HERO_08'))),registry('writer'))
        self.play(g,CARD)
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),0);self.assertFalse([e for e in g.state.players[1].player_effects if e.spec_id==PROGRAM]);self.portable(g)
    def test_d03_repeated_imbue_preserves_current_power_identity_and_cost(self):
        g=self.opening();self.seed(g,'mana');power=g.state.players[1].hero_power_id
        expected=registry('writer').card('EDR_847p').cost+1
        self.seed(g,'power_cost');self.assertEqual(g.quote_cost(power).amount,expected);self.seed(g,'nature')
        for _ in range(3):self.play(g,NATURE)
        self.assertEqual(self.count(g),2);self.assertEqual(g.state.players[1].hero_power_id,power)
        self.assertEqual(g.quote_cost(power).amount,expected);self.portable(g)

    def test_d04_going_second_coin_counts_without_changing_original_nature_condition(self):
        g=self.opening(first=2);self.assertEqual(self.count(g),1);g.apply(EndTurn(2));self.seed(g,'nature')
        self.play(g,'GAME_005');self.play(g,NATURE);self.assertEqual(self.count(g),1)
        self.play(g,NATURE);self.assertEqual(self.count(g),2)
