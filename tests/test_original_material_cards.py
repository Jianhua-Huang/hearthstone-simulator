"""Real original-material spell continuations and the minimal shared bridges."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.original_material_cards import load_batch,RETURN_ID
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Destroy,Draw,GainArmor,
    InvokeBehavior,ModifyCost,RequestChoice,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import CostSpec,SpellSchool,SummonQuantitySpec,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.summon_quantities import validate_request
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest

IMAGE='FIR_941';VICTORY='CATA_978';HIJACK='JAIL_225';ETERNAL='END_025';WIND='FIR_910';TIDE='TIME_702'
ROOTS=(IMAGE,VICTORY,HIJACK,ETERNAL,WIND,TIDE);YETI='CORE_CS2_182'


def registry():
    r=build_registry();meta=replace(r.card(YETI).metadata,collectible=False,tribes=(),deck_identity=None)
    for key,attack,health,extra in(('body',4,4,dict(battlecry='h43.cry')),('victim',1,2,{}),('huge',1,40,{}),
        ('shield',1,40,dict(keywords=(Keyword.DIVINE_SHIELD,))),('reborn',1,2,dict(keywords=(Keyword.REBORN,))),
        ('bonus',1,2,dict(spell_damage=1)),('double',1,40,dict(summon_quantities=(SummonQuantitySpec(),))),
        ('giver',1,2,dict(battlecry='h43.give'))):
        r.register_card(CardDefinition('h43.'+key,key,CardType.MINION,cost=1,attack=attack,health=health,metadata=meta,**extra))
    r.register_behavior('h43.cry',lambda c:(GainArmor(c.player_id,10),))
    r.register_behavior('h43.give',lambda c:(AddToHand(c.player_id,TIDE,c.source_id),))
    r.register_behavior('h43.fail',lambda c:(AddToHand(c.player_id,'missing.h43'),))
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Rollback',(InvokeBehavior('h43.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('h43.fire_discard',wait)
    def fact(c):return allocation_from_payload(next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==RETURN_ID).source_allocation)
    def discount(c):
        eid=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ETERNAL)
        return (ModifyCost(eid,CostSpec(set_to=1),c.source_id),)
    def bad_death(c):return (CopyCard(replace(c.state.death_history[-1],attack=c.state.death_history[-1].attack+1),c.player_id,Zone.DECK,mode='base',source_id=c.source_id),)
    scripts=dict(noop=lambda c:(),fire=lambda c:(),frost=lambda c:(),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        mark=lambda c:(Buff(c.target_id,attack=2,source_id=c.source_id),),cap=lambda c:(SetHandCapacity(c.player_id,1),),
        discount=discount,recall=lambda c:(ReturnSpentSpell(fact(c),c.player_id),),
        future_return=lambda c:(ReturnSpentSpell(replace(fact(c),zone_epoch=fact(c).zone_epoch+100),c.player_id),),
        bad_death=bad_death,summon=lambda c:(Summon(c.player_id,'h43.victim'),))
    for key,body in scripts.items():
        r.register_behavior('h43.'+key,body)
        r.register_card(CardDefinition('h43.'+key,key,CardType.SPELL,on_play='h43.'+key,
            on_discard='h43.fire_discard'if key=='fire'else None,
            spell_school=SpellSchool.FIRE if key=='fire'else SpellSchool.FROST if key=='frost'else None,
            requires_target=key in('kill','mark'),metadata=meta))
    def entry(c):
        e=c.state.entities[c.event.target_id]
        if e.card_id!='h43.body':return ()
        return (GainArmor(c.player_id,int((e.attack,e.health)==(8,8)and Keyword.DIVINE_SHIELD in e.keywords)),)
    def wait_entry(c):return wait(c)if c.state.entities[c.event.target_id].card_id=='h43.body'else ()
    def wait_draw(c):return wait(c)if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==IMAGE else ()
    def wait_death(c):return wait(c)if c.state.entities[c.event.target_id].card_id=='h43.victim'else ()
    def wait_remove(c):return wait(c)if dict(c.event.data).get('effect_key')==RETURN_ID else ()
    for key,event,body in(('entry','minion_summoned',entry),('entry_wait','minion_summoned',wait_entry),
        ('draw_wait','card_drawn',wait_draw),('death_wait','minion_died',wait_death),('return_wait','player_effect_removed',wait_remove)):
        r.register_behavior('h43.'+key,body);r.register_card(CardDefinition('h43.'+key,key,CardType.MINION,health=40,
            metadata=meta,triggers=(TriggerSpec(event,'h43.'+key),)))
    return r


class OriginalMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(YETI,)*6):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=911),self.registry)
    def play(self,g,cid,target=None):
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==cid)
        position=len(s.players[1].board)if s.entities[eid].kind==CardType.MINION else None
        g.apply(PlayCard(1,eid,target,position));return eid
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def cards(self,g,player=1,zone='board'):
        s=g.state;return [s.entities[i]for i in getattr(s.players[player],zone)]
    def armor(self,g):
        s=g.state;return s.entities[s.players[1].hero_id].armor
    def price(self,g,cid):
        s=g.state;e=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==cid)
        return quote_unselected_cost(s,g.registry,e).amount

    def test_complete_six_faces_and_lifesteal(self):
        data=load_batch();self.assertEqual({x['record']['id']for x in data['cards']},set(ROOTS))
        for row in data['cards']:
            raw=row['record'];card=self.registry.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.cost,raw['cost'])
            self.assertEqual(Keyword.LIFESTEAL in card.keywords,raw['tags'].get('LIFESTEAL')==1)

    def test_image_original_draw_and_first_entry_has_fixed_stats_and_shield_no_battlecry(self):
        g=self.game((IMAGE,),board=('h43.entry',),deck=('h43.body',));old=g.state.players[1].deck[0]
        source=self.play(g,IMAGE);s=g.state;copy=next(e for e in self.cards(g)if e.card_id=='h43.body')
        self.assertEqual((copy.attack,copy.health),(8,8));self.assertIn(Keyword.DIVINE_SHIELD,copy.keywords)
        self.assertEqual(copy.origin_entity_id,old);self.assertIn(old,s.players[1].hand);self.assertEqual(s.entities[old].attack,4)
        self.assertEqual(self.armor(g),1)
        material=s.card_summon_history[-1].request.materials[0];self.assertEqual(material.grant_source_id,source)
        self.assertEqual(material.minion_grant.keywords,(Keyword.DIVINE_SHIELD,));self.portable(g)

    def test_image_quantity_copies_all_receive_entry_grant(self):
        g=self.game((IMAGE,),board=('h43.double',),deck=('h43.body',));self.play(g,IMAGE)
        copies=[e for e in self.cards(g)if e.card_id=='h43.body'];self.assertEqual(len(copies),2)
        self.assertTrue(all((e.attack,e.health)==(8,8)and Keyword.DIVINE_SHIELD in e.keywords for e in copies));self.portable(g)

    def test_image_empty_or_full_board_preserves_real_draw(self):
        g=self.game((IMAGE,),deck=('h43.noop',));self.play(g,IMAGE);self.assertFalse(g.state.draw_history)
        g=self.game((IMAGE,),board=('h43.huge',)*7,deck=('h43.body',));self.play(g,IMAGE)
        self.assertEqual(len(self.cards(g)),7);self.assertEqual([e.card_id for e in self.cards(g,zone='hand')],['h43.body'])

    def test_image_draw_wait_and_entry_wait_restore_rollback_replay(self):
        for watcher in('h43.draw_wait','h43.entry_wait'):
            g=self.game((IMAGE,),board=(watcher,),deck=('h43.body',));self.play(g,IMAGE);before=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),before);other=self.portable(g)
            for current in(g,other):self.choose(current)
            self.assertEqual(g.snapshot(),other.snapshot())
            copy=next(e for e in self.cards(g)if e.card_id=='h43.body');self.assertIn(Keyword.DIVINE_SHIELD,copy.keywords)

    def test_copy_entry_grant_source_cannot_be_substituted(self):
        g=self.game((IMAGE,),deck=('h43.body',));self.play(g,IMAGE);s=g.state
        request=s.card_summon_history[-1].request;material=request.materials[0]
        wrong=replace(material,grant_source_id=s.players[2].hero_id)
        with self.assertRaises(ValueError):validate_request(s,g.registry,replace(request,materials=(wrong,)),closed=True)
        ref=CardReference.capture(s.entities[s.players[1].hand[0]])
        with self.assertRaises(ValueError):CopyStoredMinion(ref,1,minion_grant=CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD,)))

    def test_victory_excess_uses_actual_health_result_and_clamps_cost(self):
        g=self.game((VICTORY,'h43.body'),enemy=('h43.victim',));self.play(g,VICTORY,g.state.players[2].board[0])
        self.assertEqual(self.price(g,'h43.body'),0)
        g=self.game((VICTORY,YETI),enemy=('h43.huge',));self.play(g,VICTORY,g.state.players[2].board[0]);self.assertEqual(self.price(g,YETI),4)

    def test_victory_shield_and_empty_hand_skip_reward(self):
        g=self.game((VICTORY,YETI),enemy=('h43.shield',));self.play(g,VICTORY,g.state.players[2].board[0]);self.assertEqual(self.price(g,YETI),4)
        g=self.game((VICTORY,),enemy=('h43.victim',));self.play(g,VICTORY,g.state.players[2].board[0]);self.assertFalse(g.state.players[1].hand)

    def test_victory_bonus_excess_and_only_one_random_hand_card(self):
        g=self.game((VICTORY,YETI,YETI),board=('h43.bonus',),enemy=('h43.victim',));self.play(g,VICTORY,g.state.players[2].board[0]);s=g.state
        self.assertEqual(sorted(quote_unselected_cost(s,g.registry,s.entities[i]).amount for i in s.players[1].hand),[0,4])

    def test_hijack_printed_copy_cost_two_uses_original_death_and_new_owner(self):
        g=self.game(('h43.mark',HIJACK),enemy=('h43.victim',),deck=());target=g.state.players[2].board[0]
        self.play(g,'h43.mark',target);self.play(g,HIJACK,target);s=g.state;new=s.entities[s.players[1].deck[0]]
        self.assertNotEqual(new.id,target);self.assertEqual(new.origin_entity_id,target)
        self.assertEqual((new.owner,new.controller,new.attack,new.health,new.base_cost),(1,1,1,2,1))
        self.assertEqual(quote_unselected_cost(s,g.registry,new).amount,2)
        self.assertEqual(s.entities[target].zone,Zone.GRAVEYARD)

    def test_hijack_reborn_does_not_copy_new_body_and_nonlethal_skips(self):
        g=self.game((HIJACK,),enemy=('h43.reborn',),deck=());old=g.state.players[2].board[0];self.play(g,HIJACK,old);s=g.state
        self.assertEqual(len(s.players[1].deck),1);copy=s.entities[s.players[1].deck[0]]
        self.assertEqual(copy.origin_entity_id,old);self.assertEqual(copy.health,2);self.assertIn(Keyword.REBORN,copy.keywords)
        g=self.game((HIJACK,),enemy=('h43.huge',),deck=());self.play(g,HIJACK,g.state.players[2].board[0]);self.assertFalse(g.state.players[1].deck)

    def test_hijack_death_wait_preserves_full_original_record(self):
        g=self.game((HIJACK,),board=('h43.death_wait',),enemy=('h43.victim',),deck=());self.play(g,HIJACK,g.state.players[2].board[0]);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].deck),1)

    def test_death_copy_rejects_uncommitted_modified_record(self):
        g=self.game(('h43.kill','h43.bad_death'),enemy=('h43.victim',));self.play(g,'h43.kill',g.state.players[2].board[0]);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h43.bad_death')
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ValueError):CopyCard(g.state.death_history[-1],1,Zone.DECK,mode='current')

    def test_eternal_returns_same_spell_at_owner_end_and_resets_local_price(self):
        g=self.game(('h43.discount',ETERNAL),enemy=('h43.victim',));self.play(g,'h43.discount')
        source=self.play(g,ETERNAL,g.state.players[2].board[0]);s=g.state
        self.assertEqual(s.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(s.players[1].player_effects),1)
        self.portable(g);g.apply(EndTurn(1));s=g.state
        self.assertIn(source,s.players[1].hand);self.assertEqual(s.entities[source].zone_epoch,2)
        self.assertEqual(self.price(g,ETERNAL),3);self.assertFalse(s.players[1].player_effects)

    def test_eternal_nonlethal_or_shield_does_not_schedule_return(self):
        for target in('h43.huge','h43.shield'):
            g=self.game((ETERNAL,),enemy=(target,));source=self.play(g,ETERNAL,g.state.players[2].board[0]);g.apply(EndTurn(1))
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.players[1].player_effects)

    def test_eternal_multiple_independent_returns_do_not_consume_secret_slots(self):
        g=self.game((ETERNAL,)*6,enemy=('h43.victim',)*6);sources=[]
        for _ in range(6):sources.append(self.play(g,ETERNAL,g.state.players[2].board[0]))
        self.assertEqual(len(g.state.players[1].player_effects),6);g.apply(EndTurn(1));s=g.state
        self.assertEqual(set(s.players[1].hand),set(sources));self.assertFalse(s.players[1].player_effects)

    def test_eternal_old_grave_reference_cannot_duplicate_recalled_and_recast_spell(self):
        g=self.game((ETERNAL,'h43.recall'),enemy=('h43.victim','h43.victim'))
        source=self.play(g,ETERNAL,g.state.players[2].board[0]);self.play(g,'h43.recall')
        self.assertIn(source,g.state.players[1].hand);self.play(g,ETERNAL,g.state.players[2].board[0]);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand.count(source),1);self.assertFalse(g.state.players[1].player_effects)

    def test_eternal_full_hand_burns_original_delivery_without_death_or_discard(self):
        g=self.game(('h43.cap',ETERNAL,'h43.noop'),enemy=('h43.victim',));self.play(g,'h43.cap')
        source=self.play(g,ETERNAL,g.state.players[2].board[0]);g.apply(EndTurn(1));s=g.state
        self.assertEqual(s.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(s.players[1].player_effects)
        self.assertFalse(s.discard_history);self.assertEqual(len(s.death_history),1)
        self.assertTrue(any(e.kind=='card_burned'and e.target_id==source for e in g.events));self.portable(g)

    def test_eternal_return_wait_after_effect_consumed_recovers_and_rolls_back(self):
        g=self.game((ETERNAL,),board=('h43.return_wait',),enemy=('h43.victim',));source=self.play(g,ETERNAL,g.state.players[2].board[0])
        g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(source,g.state.players[1].hand)

    def test_spent_return_rejects_future_allocation_and_rolls_back_action(self):
        g=self.game((ETERNAL,'h43.future_return'),enemy=('h43.victim',));self.play(g,ETERNAL,g.state.players[2].board[0]);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h43.future_return')
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ValueError):ReturnSpentSpell(allocation_from_payload(g.state.players[1].player_effects[0].source_allocation),2)

    def test_wind_only_discards_fire_and_hits_original_target_twice(self):
        g=self.game((WIND,'h43.fire','h43.frost'),enemy=('h43.huge',));target=g.state.players[2].board[0]
        self.play(g,WIND,target);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertEqual(g.state.entities[target].health,34);self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual([e.card_id for e in self.cards(g,zone='hand')],['h43.frost'])

    def test_wind_no_fire_skips_second_damage_and_rng(self):
        g=self.game((WIND,'h43.frost'),enemy=('h43.huge',));target=g.state.players[2].board[0];before=g._rng.getstate()
        self.play(g,WIND,target);self.assertEqual(g.state.entities[target].health,37)
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(g.state.discard_history)

    def test_wind_reborn_is_not_the_original_second_target(self):
        g=self.game((WIND,'h43.fire'),enemy=('h43.reborn',));self.play(g,WIND,g.state.players[2].board[0]);self.choose(g)
        self.assertEqual(self.cards(g,2)[0].health,1);self.assertEqual(len(g.state.discard_history),1)

    def test_wind_discard_body_wait_keeps_success_continuation_and_original_target(self):
        g=self.game((WIND,'h43.fire'),enemy=('h43.huge',));target=g.state.players[2].board[0];self.play(g,WIND,target);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].health,34)

    def test_tide_minion_commit_while_held_qualifies(self):
        g=self.game((TIDE,'h43.victim'));self.play(g,'h43.victim');s=g.state;self.play(g,TIDE,s.players[2].hero_id)
        self.assertEqual(self.armor(g),5);self.assertEqual(g.state.entities[s.players[2].hero_id].health,27)

    def test_tide_spell_or_direct_summon_does_not_qualify(self):
        for other in('h43.noop','h43.summon'):
            g=self.game((TIDE,other));self.play(g,other);s=g.state;self.play(g,TIDE,s.players[2].hero_id)
            self.assertEqual(self.armor(g),0)

    def test_tide_acquired_during_minion_battlecry_does_not_retroactively_qualify(self):
        g=self.game(('h43.giver',));self.play(g,'h43.giver');s=g.state;self.play(g,TIDE,s.players[2].hero_id)
        self.assertEqual(self.armor(g),0)

    def test_tide_progress_survives_portable_hand_state(self):
        g=self.game((TIDE,'h43.victim'));self.play(g,'h43.victim');other=self.portable(g)
        for current in(g,other):self.play(current,TIDE,current.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),5)

    def test_own_player_views_do_not_expose_copy_grant_or_spent_allocation_proofs(self):
        g=self.game((IMAGE,ETERNAL),deck=('h43.body',),enemy=('h43.victim',));self.play(g,IMAGE)
        self.play(g,ETERNAL,g.state.players[2].board[0])
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))
            for token in('grant_source_id','source_allocation','CopyEntryMaterial','zone_epoch','next_attachment_id'):self.assertNotIn(token,visible)

    def test_old_schema_is_rejected(self):
        saved=self.game().snapshot();saved['schema_version']=274
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
