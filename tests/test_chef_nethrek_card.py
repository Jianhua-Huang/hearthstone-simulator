"""Chef's real opening and owner deadline; scoped shared-account checks."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.chef_nethrek_card import CONDITION, PREFIX, PROGRAM, ROOT, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, MatchSetup, PlayCard, PlayerSetup,
    Rarity, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption,
    Destroy, GainTemporaryMana, InvokeBehavior, Overload, RandomDamage,
    RefreshMana, RequestChoice, SetManaCap, SpendMana)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.player_effects import timed_count
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import area_count
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyStoredCard

P='chef.test.'
HIGH, WATCH, ASSIGN, BAD_OPEN=(P+x for x in ('high', 'watch', 'assign', 'bad_open'))
FILLERS=tuple(P+'filler.'+str(i) for i in range(30))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r=build_registry(); meta=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
    def fail(c): raise ResolutionError('Chef deliberate rollback')
    r.register_behavior(P+'fail', fail)
    def destroy(c, cid):
        if cid==ROOT:
            instance=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==PROGRAM)
            source=c.state.entities[instance.source_id]
        else:
            source=next(e for e in c.state.entities.values() if e.card_id==cid and e.controller==c.player_id and e.zone in (Zone.HAND, Zone.DECK))
        return (DestroyStoredCard(CardReference.capture(source), source_id=c.source_id),) if source.zone in (Zone.HAND, Zone.DECK) else (Destroy(source.id,c.source_id),)
    r.register_behavior(P+'destroy', lambda c: destroy(c,ROOT))
    r.register_behavior(P+'remove_high', lambda c: destroy(c,HIGH))
    def seed(c):
        options=(
            ChoiceOption('none','No change',()),
            ChoiceOption('watch','Observe assignment',(AddToHand(c.player_id,WATCH,c.source_id),)),
            ChoiceOption('spend','Spend current mana',(SpendMana(c.player_id,None,c.source_id),)),
            ChoiceOption('ramp','Early ramp',(ChangeManaCrystals(c.player_id,2,filled=True),RefreshMana(c.player_id,20))),
            ChoiceOption('overload','Overload next owner turn',(Overload(c.player_id,2),)),
            ChoiceOption('temp','Temporary mana',(GainTemporaryMana(c.player_id,2),)),
            ChoiceOption('high','Add current high-cost card',(AddToDeck(c.player_id,HIGH,source_id=c.source_id),)),
            ChoiceOption('remove_high','Remove original high card',(InvokeBehavior(P+'remove_high',c.source_id,c.player_id),)),
            ChoiceOption('destroy','Remove original Chef',(InvokeBehavior(P+'destroy',c.source_id,c.player_id),)),
            ChoiceOption('late','Generate Chef later',(AddToHand(c.player_id,ROOT,c.source_id),)))
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(P+'seed',seed)
    for cid in FILLERS:
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=2,on_play=P+'seed',metadata=meta))
    r.register_card(CardDefinition(HIGH,HIGH,CardType.MINION,cost=4,health=8,metadata=meta))
    def watch(c):
        if c.event.player_id!=c.player_id or dict(c.event.data).get('operation')!='ChangeManaCrystals':return ()
        if c.state.players[c.player_id].max_mana!=10:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('spend','Spend one new mana',(SpendMana(c.player_id,1,c.source_id),)),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=replace(meta,collectible=False),
        triggers=(TriggerSpec('mana_changed',P+'watch'),)))
    def driver(c, opening=False):
        source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ROOT)
        return (InvokeBehavior(PREFIX+('opening' if opening else 'assign'),source,c.player_id),)
    for cid, opening in ((ASSIGN,False),(BAD_OPEN,True)):
        r.register_behavior(cid,lambda c,opening=opening: driver(c,opening))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    r.validate();r.freeze();return r


class ChefNethrekTests(unittest.TestCase):
    def opening(self, *, include=True, high=False, both=False, first=1, complete=True):
        r=registry('writer')
        cards=(ROOT,HIGH,*FILLERS[:28]) if include and high else (ROOT,*FILLERS[:29]) if include else FILLERS
        other=(ROOT,*FILLERS[:29]) if both else FILLERS
        decks=(DeckSpec('HERO_06','HERO_06bp',CardClass.DRUID,cards),
               DeckSpec('HERO_06','HERO_06bp',CardClass.DRUID,other))
        policy=DeckPolicy(P+'policy','cn37-synthetic-chef','experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=245860,first_player=first),r)
        if complete:self.finish_opening(g)
        return g
    def finish_opening(self,g,all_cards=False):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;self.assertIn('mulligan',str(q.purpose))
            g.apply(SelectChoice(q.player_id,q.id,tuple(o.id for o in q.options) if all_cards else ()))
    def program(self,g,pid=1):return tuple(e for e in g.state.players[pid].player_effects if e.spec_id==PROGRAM)
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,eid))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def seed(self,g,key):
        cid=next(g.state.entities[i].card_id for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id in FILLERS)
        self.play(g,cid);self.choose(g,key)
    def advance(self,g,pid=1,index=5):
        while g.state.active_player!=pid or current_owner_turn(g.state).owner_index<index:
            g.apply(EndTurn(g.state.active_player))
    def portable(self,g):
        r=registry('reader' if g.registry is registry('writer') else 'writer')
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        for candidate in (other,g.clone(),replay(build_replay(g),r)):
            self.assertEqual(candidate.snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('"original_deck"','"source_allocation"','"resolution_frame"','"rng_state"'):
                self.assertNotIn(key,wire)
        return other
    def deadline_wait(self):
        g=self.opening();self.seed(g,'watch');self.play(g,WATCH)
        self.advance(g);self.seed(g,'spend');g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);return g

    def test_a00_complete_source_faces_printed_three_and_original_internal_four_preserved(self):
        from tools.card_batch import check_face
        d=load_batch();raw=d['cards'][0]['record']
        for item in d['official_observations']:check_face(raw,item['face'],item['locale'])
        self.assertEqual((raw['cost'],raw['attack'],raw['health'],raw['tags']['CHEF_NETHREK_REQUIREMENT']),(3,3,3,4))
        self.assertEqual((CONDITION.cost_limit,CONDITION.cost_basis,CONDITION.scope),(3,'printed','starting'))
        self.assertNotIn('JAIL_860e',registry('writer').cards)

    def test_a01_actual_thirty_card_start_installs_once_before_mulligan_without_timed_area(self):
        g=self.opening(complete=False);self.assertEqual(len(self.program(g)),1)
        original=self.program(g)[0].id
        self.assertEqual((timed_count(g.state.players[1],g.registry),area_count(g.state.players[1],g.registry)),(0,0))
        self.finish_opening(g,True);self.assertEqual(self.program(g)[0].id,original);self.portable(g)

    def test_b00_fifth_natural_owner_end_for_both_players_and_both_first_player_orders(self):
        for first in (1,2):
            with self.subTest(first=first):
                g=self.opening(both=True,first=first)
                for _ in range(10):
                    pid=g.state.active_player;index=current_owner_turn(g.state).owner_index
                    self.assertEqual(g.state.players[pid].max_mana,index)
                    g.apply(EndTurn(pid));p=g.state.players[pid]
                    self.assertEqual(p.max_mana,10 if index==5 else index)
                    self.assertEqual(bool(self.program(g,pid)),index<5)
                self.assertEqual([g.state.players[p].mana for p in (1,2)],[10,10]);self.portable(g)

    def test_b01_consumed_instance_does_not_refill_again_on_later_owner_ends(self):
        g=self.opening();self.advance(g);g.apply(EndTurn(1));self.advance(g,index=6)
        self.assertFalse(self.program(g));self.seed(g,'spend');g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,0));self.portable(g)

    def test_b02_early_ramp_does_not_advance_or_disable_original_deadline(self):
        g=self.opening();self.seed(g,'ramp');self.advance(g,index=4)
        self.assertEqual(g.state.players[1].max_mana,6);self.assertTrue(self.program(g))
        self.advance(g);self.assertEqual(g.state.players[1].max_mana,7);g.apply(EndTurn(1))
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,10));self.portable(g)

    def test_b03_destroying_original_chef_does_not_remove_accepted_start_program(self):
        g=self.opening();source=self.program(g)[0].source_id;self.seed(g,'destroy')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertTrue(self.program(g))
        self.advance(g);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].max_mana,10);self.portable(g)

    def test_c00_original_four_cost_card_prevents_installation(self):
        g=self.opening(high=True);self.assertFalse(self.program(g))
        self.advance(g);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].max_mana,5);self.portable(g)

    def test_c01_later_current_high_card_does_not_revoke_original_qualification(self):
        g=self.opening();self.seed(g,'high');self.assertNotIn(HIGH,g.state.players[1].original_deck)
        self.assertTrue(any(g.state.entities[i].card_id==HIGH for i in g.state.players[1].deck))
        self.advance(g);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].max_mana,10);self.portable(g)

    def test_c02_removing_original_high_card_does_not_retroactively_install(self):
        g=self.opening(high=True);self.seed(g,'remove_high');self.assertIn(HIGH,g.state.players[1].original_deck)
        self.assertFalse(self.program(g));self.advance(g);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].max_mana,5);self.portable(g)

    def test_c03_generated_later_chef_has_no_retroactive_start_of_game(self):
        g=self.opening(include=False);self.seed(g,'late');self.advance(g,index=3);self.play(g,ROOT)
        self.assertFalse(self.program(g));self.advance(g);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].max_mana,5);self.portable(g)

    def test_d00_real_mulligan_wait_restores_independent_registry_clone_and_replay(self):
        g=self.opening(complete=False);g=self.portable(g);self.finish_opening(g)
        self.assertEqual(len(self.program(g)),1);self.portable(g)

    def test_d01_deadline_wait_keeps_exact_consumption_and_original_spent_continuation(self):
        g=self.deadline_wait();self.assertFalse(self.program(g))
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,5))
        g=self.portable(g);self.choose(g)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,10));self.portable(g)

    def test_d02_failed_deadline_choice_restores_rng_accounts_and_consumed_instance_state(self):
        g=self.deadline_wait();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_d03_intervening_new_spend_is_not_refunded_as_original_spent_mana(self):
        g=self.deadline_wait();g=self.portable(g);self.choose(g,'spend')
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,9));self.portable(g)

    def test_e00_assignment_composition_uses_current_shared_cap_overload_and_temporary_accounts(self):
        # Isolated shared-account harness, separate from actual opening/deadline
        # tests above. It executes the same fresh private assignment callback.
        cases=[
            (dict(max_mana=5,mana=0), (10,10,0,0,0)),
            (dict(max_mana=5,mana=0,overload_locked=2,overload_owed=3), (10,8,0,2,3)),
            (dict(max_mana=4,mana=0,mana_cap=5), (5,5,0,0,0)),
            (dict(max_mana=12,mana=0,mana_cap=20), (10,10,0,0,0)),
            (dict(max_mana=5,mana=5,temporary_mana=2), (10,12,2,0,0)),
        ]
        for setup,expected in cases:
            with self.subTest(setup=setup):
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=(ASSIGN,),board=(ROOT,),**setup),PlayerSetup('HERO_08'))),registry('writer'))
                self.play(g,ASSIGN);p=g.state.players[1]
                self.assertEqual((p.max_mana,p.mana,p.temporary_mana,p.overload_locked,p.overload_owed),expected)
                self.portable(g)

    def test_e01_opening_callback_rejects_nonopening_context_and_rolls_back(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=(BAD_OPEN,),board=(ROOT,)),PlayerSetup('HERO_08'))),registry('writer'))
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD_OPEN)
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
