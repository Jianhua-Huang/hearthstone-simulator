"""Real six-cost summon dependencies use native lifecycle and exact results."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.six_cost_native_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.attack_policies import attack_policy_error
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,GainArmor,
    GainResource,InvokeBehavior,RequestChoice,Silence,CopyMinion,ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CostSpec,DamageKind,Resource
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import canonical_digest

MARROW='CORE_RLK_505';MERITHRA='EDR_238';FLAME='FIR_940';GNOME='RLK_720';MACHINE='TIME_043'
HOUR='TIME_050';STALKER='TIME_605';STEGO='TLC_401';KODO='TLC_454';OPU='TLC_522';NABLYA='TLC_624';FAN='EX1_129'
SMALL='k47.small';BIG='k47.big';OTHER='k47.other';CHEAP='k47.cheap';WALL='k47.wall';TAUNT='k47.taunt';SHIELD='k47.shield'


def registry():
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,cost,atk,hp,tribes,keys in ((SMALL,1,2,4,('beast',),(Keyword.CHARGE,)),
        (BIG,8,8,8,('dragon',),()),(OTHER,9,9,9,('beast',),()),(CHEAP,7,7,7,('beast',),()),
        (WALL,2,1,10,(),()),(TAUNT,3,1,15,(),(Keyword.TAUNT,)),(SHIELD,4,3,5,(),(Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,
            keywords=keys,metadata=replace(meta,tribes=tribes)))
    scripts=dict(ping=lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        hit3=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        blast=lambda c:(Damage(c.target_id,12,c.source_id,DamageKind.SPELL),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        grow=lambda c:(Buff(c.target_id,2,2,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),
        noop=lambda c:(),
        fail=lambda c:(AddToHand(c.player_id,'unknown.k47',c.source_id),),
        discount=lambda c:tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SMALL))
    for name,body in scripts.items():
        key='k47.'+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=meta,
            requires_target=name in('ping','hit3','blast','kill','grow','silence')))
    r.register_behavior('k47.seed_death',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(SMALL),),SummonCause.capture(c)),))
    r.register_card(CardDefinition('k47.seed','Death checkpoint seed',CardType.MINION,attack=1,health=1,
        deathrattle='k47.seed_death',metadata=meta))
    def reenter(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SMALL)
        return(SummonStoredCard(CardReference.capture(e),c.player_id,cause=SummonCause.capture(c)),)
    def deferred(c):
        target=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SMALL)
        copy=CopyMinion(BoardPresenceReference.capture(c.state,target),c.player_id,cause=SummonCause.capture(c))
        return(RequestChoice(c.player_id,(ChoiceOption('stay','Copy',(copy,)),ChoiceOption('leave','Reenter',
            (ReturnToHand(target),InvokeBehavior('k47.reenter',c.source_id,c.player_id),copy))),c.source_id),)
    r.register_behavior('k47.reenter',reenter);r.register_behavior('k47.deferred',deferred)
    r.register_card(CardDefinition('k47.deferred','Deferred residence probe',CardType.SPELL,on_play='k47.deferred',metadata=meta))
    def waiting(c,resource=False):
        if resource:
            if c.event.source_id!=c.source_id and c.state.entities[c.event.source_id].card_id!=MARROW:return ()
        elif c.state.entities[c.event.target_id].origin_entity_id is None:return ()
        effects=(GainResource(c.player_id,Resource.CORPSES,3),)if resource else(GainArmor(c.player_id,1),)
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
            ChoiceOption('bad','Fail',(InvokeBehavior('k47.fail',c.source_id,c.player_id),))),c.source_id),)
    for name,event,resource in(('resource_wait','resource_spent',True),('copy_wait','minion_summoned',False)):
        key='k47.'+name;r.register_behavior(key,lambda c,resource=resource:waiting(c,resource))
        r.register_card(CardDefinition(key,name,CardType.MINION,health=10,metadata=meta,triggers=(TriggerSpec(event,key),)))
    return r


class SixCostNativeCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(SMALL,)*10,corpses=0,active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            corpses=corpses,mana=60,max_mana=60,mana_cap=60,hand_cap=20),PlayerSetup('HERO_08',board=enemy,
            hand=enemy_hand,deck=(SMALL,)*10,mana=60,max_mana=60,mana_cap=60,hand_cap=20)),active_player=active,seed=947),self.r)
    def eid(self,g,cid,zone='hand',p=1):
        s=g.state;return next(i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        s=g.state;eid=self.eid(g,cid,p=p);g.apply(PlayCard(p,eid,target,
            position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None));return eid
    def price(self,g,eid):
        s=g.state;return quote_unselected_cost(s,g.registry,s.entities[eid]).amount
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hits(self,g,source):
        return [e for e in g.events if e.kind=='damage_dealt'and e.source_id==source]
    def board(self,g,p=1):
        s=g.state;return [s.entities[i]for i in s.players[p].board]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def test_complete_eleven_roots_and_required_named_fan(self):
        data=load_batch();self.assertEqual(len(data['cards']),12)
        self.assertEqual(sum(x['recipe']['root']for x in data['cards']),11)
        for row in data['cards']:
            raw=row['record'];card=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack']or 0,raw['health']or 0))
        self.assertEqual(self.r.card(MARROW).metadata.deck_identity,'RLK_505')
        self.assertEqual(self.r.card(FAN).cost,2);self.assertEqual(self.r.card(STALKER).metadata.tribes,('beast',))

    def test_marrow_debits_only_available_corpses_and_never_more_than_five(self):
        for balance,count in((0,0),(2,2),(7,5)):
            with self.subTest(balance=balance):
                g=self.game((MARROW,),corpses=balance);source=self.play(g,MARROW)
                self.assertEqual(len(self.hits(g,source)),count)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES],balance-count)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30-2*count)

    def test_marrow_single_payment_and_actual_capped_debit_receipt(self):
        g=self.game((MARROW,),corpses=7);mana=g.state.players[1].mana;source=self.play(g,MARROW)
        self.assertEqual(g.state.players[1].mana,mana-6)
        rows=[e for e in g.events if e.kind=='resource_spent'and e.source_id==source]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].amount,5);self.portable(g)

    def test_marrow_requeries_after_a_previous_missile_kills_a_minion(self):
        g=self.game(('k47.hit3',MARROW),corpses=5,enemy=(SMALL,));enemy=self.eid(g,SMALL,'board',2)
        self.play(g,'k47.hit3',enemy);source=self.play(g,MARROW);hits=self.hits(g,source)
        self.assertEqual(len(hits),5);self.assertLessEqual(sum(e.target_id==enemy for e in hits),1)
        self.assertTrue(all(e.amount==2 for e in hits));self.portable(g)

    def test_marrow_wait_restore_keeps_original_count_after_refund(self):
        g=self.game((MARROW,),corpses=2,board=('k47.resource_wait',));source=self.play(g,MARROW)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertEqual(self.hits(g,source),[]);g=self.portable(g);self.choose(g)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],3)
        self.assertEqual(len(self.hits(g,source)),2);self.portable(g)

    def test_marrow_failed_wait_submission_rolls_back_to_original_choice(self):
        g=self.game((MARROW,),corpses=2,board=('k47.resource_wait',));self.play(g,MARROW);saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertIsNone(g.state.pending_choice)

    def test_merithra_resurrects_distinct_friendly_printed_eight_plus(self):
        g=self.game(('k47.kill','k47.kill','k47.kill','k47.kill',MERITHRA),board=(BIG,BIG,OTHER,CHEAP))
        for cid in(BIG,BIG,OTHER,CHEAP):self.play(g,'k47.kill',self.eid(g,cid,'board'))
        self.play(g,MERITHRA);cards=[e.card_id for e in self.board(g)]
        self.assertCountEqual(cards,[MERITHRA,BIG,OTHER]);self.portable(g)

    def test_merithra_does_not_resurrect_opponents_or_seven_cost_deaths(self):
        g=self.game(('k47.kill','k47.kill',MERITHRA),board=(CHEAP,),enemy=(BIG,))
        self.play(g,'k47.kill',self.eid(g,CHEAP,'board'));self.play(g,'k47.kill',self.eid(g,BIG,'board',2))
        before=g._rng.getstate();self.play(g,MERITHRA)
        self.assertEqual([e.card_id for e in self.board(g)],[MERITHRA]);self.assertEqual(g._rng.getstate(),before)

    def test_merithra_respects_actual_remaining_board_space(self):
        g=self.game(('k47.kill',MERITHRA),board=(BIG,)+(SMALL,)*5)
        self.play(g,'k47.kill',self.eid(g,BIG,'board'));self.play(g,MERITHRA)
        self.assertEqual(len(self.board(g)),7);self.assertEqual(sum(e.card_id==BIG for e in self.board(g)),1)

    def test_flamebinder_reduces_every_card_when_current_prices_are_unique(self):
        g=self.game((FLAME,SMALL,BIG,FAN));ids=list(g.state.players[1].hand)[1:];self.play(g,FLAME)
        self.assertEqual([self.price(g,i)for i in ids],[0,6,0]);self.portable(g)

    def test_flamebinder_shared_printed_prices_fail_without_changes(self):
        g=self.game((FLAME,SMALL,SMALL));ids=list(g.state.players[1].hand)[1:];self.play(g,FLAME)
        self.assertEqual([self.price(g,i)for i in ids],[1,1])

    def test_flamebinder_uses_current_cost_including_existing_modifiers(self):
        g=self.game(('k47.discount',FLAME,SMALL,FAN));self.play(g,'k47.discount')
        small=self.eid(g,SMALL);fan=self.eid(g,FAN);self.assertEqual(self.price(g,small),0)
        self.play(g,FLAME);self.assertEqual((self.price(g,small),self.price(g,fan)),(0,0))

    def test_flamebinder_does_not_touch_future_draws(self):
        g=self.game((FLAME,SMALL),deck=(BIG,));self.play(g,FLAME);self.cycle(g)
        self.assertEqual(self.price(g,self.eid(g,BIG)),8)

    def test_gnome_attacks_lowest_health_enemy_and_uses_combat_lifesteal(self):
        g=self.game(('k47.hit3',),board=(GNOME,),enemy=(SMALL,TAUNT));source=self.eid(g,GNOME,'board')
        self.play(g,'k47.hit3',g.state.players[1].hero_id);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(g.state.entities[source].health,4)
        self.assertEqual(g.state.entities[self.eid(g,TAUNT,'board',2)].health,15)
        self.assertFalse(any(e.card_id==SMALL for e in self.board(g,2)));self.portable(g)

    def test_gnome_does_not_attack_at_opponents_end(self):
        g=self.game(board=(GNOME,),enemy=(SMALL,),active=2);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[self.eid(g,SMALL,'board',2)].health,4)
        self.assertFalse(any(e.kind=='attack_declared'for e in g.events))

    def test_gnome_can_force_combat_into_lowest_health_hero(self):
        g=self.game(board=(GNOME,),enemy=(TAUNT,));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        # A 15-health Taunt is lower than the 30-health hero, so it is selected.
        self.assertEqual(g.state.entities[self.eid(g,TAUNT,'board',2)].health,10)
        h=self.game(board=(GNOME,));h.apply(EndTurn(1));self.assertEqual(h.state.entities[h.state.players[2].hero_id].health,25)

    def test_gnome_silence_removes_the_end_trigger(self):
        g=self.game(('k47.silence',),board=(GNOME,));self.play(g,'k47.silence',self.eid(g,GNOME,'board'))
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_infinitizer_sets_and_heals_then_expires_only_attack_restriction(self):
        g=self.game(('k47.hit3',MACHINE),board=(SMALL,));target=self.eid(g,SMALL,'board')
        self.play(g,'k47.hit3',target);self.play(g,MACHINE,target);s=g.state;e=s.entities[target]
        self.assertEqual((e.attack,e.health,e.max_health),(8,8,8))
        self.assertIsNotNone(attack_policy_error(s,e,s.entities[s.players[2].hero_id],g.registry))
        self.cycle(g);s=g.state;e=s.entities[target]
        self.assertEqual((e.attack,e.health),(8,8));self.assertIsNone(attack_policy_error(s,e,s.entities[s.players[2].hero_id],g.registry));self.portable(g)

    def test_infinitizer_can_be_played_without_friendly_target(self):
        g=self.game((MACHINE,));self.play(g,MACHINE);self.assertEqual(len(self.board(g)),1)

    def test_infinitizer_target_can_still_attack_a_minion(self):
        g=self.game((MACHINE,),board=(SMALL,),enemy=(BIG,));target=self.eid(g,SMALL,'board')
        enemy=self.eid(g,BIG,'board',2);self.play(g,MACHINE,target);g.apply(Attack(1,target,enemy))
        self.assertFalse(any(e.card_id==BIG for e in self.board(g,2)))

    def test_hourglass_swaps_remaining_health_after_actual_survived_damage(self):
        g=self.game(('k47.ping','k47.ping'),board=(HOUR,));source=self.eid(g,HOUR,'board')
        self.play(g,'k47.ping',source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,4))
        self.play(g,'k47.ping',source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,8));self.portable(g)

    def test_hourglass_does_not_swap_for_another_minions_damage(self):
        g=self.game(('k47.ping',),board=(HOUR,SMALL));source=self.eid(g,HOUR,'board')
        self.play(g,'k47.ping',self.eid(g,SMALL,'board'));self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,9))

    def test_hourglass_silence_disables_its_swap(self):
        g=self.game(('k47.silence','k47.ping'),board=(HOUR,));source=self.eid(g,HOUR,'board')
        self.play(g,'k47.silence',source);self.play(g,'k47.ping',source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,8))

    def test_hourglass_lethal_damage_does_not_swap_back_into_life(self):
        g=self.game(('k47.blast',),board=(HOUR,));source=self.eid(g,HOUR,'board')
        self.play(g,'k47.blast',source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertFalse(any(e.card_id==HOUR for e in self.board(g)));self.portable(g)

    def test_stalker_summons_one_current_copy_without_repeating_battlecry(self):
        g=self.game((STALKER,));self.play(g,STALKER);cards=self.board(g);self.assertEqual(len(cards),2)
        self.assertTrue(all((e.attack,e.health)==(3,4)for e in cards))
        self.assertTrue(all({Keyword.RUSH,Keyword.ELUSIVE}<=e.keywords for e in cards))
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_stalker_full_board_cannot_deliver_the_copy(self):
        g=self.game((STALKER,),board=(SMALL,)*6);self.play(g,STALKER)
        self.assertEqual(sum(e.card_id==STALKER for e in self.board(g)),1)

    def test_stalker_copy_wait_restores_successful_delivery(self):
        g=self.game((STALKER,),board=('k47.copy_wait',));self.play(g,STALKER)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual(sum(e.card_id==STALKER for e in self.board(g)),2);self.portable(g)

    def test_stegodon_deathrattle_hits_three_distinct_enemy_characters(self):
        g=self.game(('k47.kill',),board=(STEGO,),enemy=(WALL,WALL,WALL,WALL));source=self.eid(g,STEGO,'board')
        self.play(g,'k47.kill',source);hits=self.hits(g,source)
        self.assertEqual(len(hits),3);self.assertEqual(len({e.target_id for e in hits}),3)
        self.assertTrue(all(e.amount==6 for e in hits));self.portable(g)

    def test_stegodon_small_pool_hits_each_enemy_at_most_once(self):
        g=self.game(('k47.kill',),board=(STEGO,),enemy=(WALL,));source=self.eid(g,STEGO,'board')
        self.play(g,'k47.kill',source);hits=self.hits(g,source)
        self.assertEqual(len(hits),2);self.assertEqual(len({e.target_id for e in hits}),2)

    def test_stegodon_divine_shield_uses_normal_damage_prevention(self):
        g=self.game(('k47.kill',),board=(STEGO,),enemy=(SHIELD,));enemy=self.eid(g,SHIELD,'board',2)
        self.play(g,'k47.kill',self.eid(g,STEGO,'board'))
        self.assertEqual(g.state.entities[enemy].health,5);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[enemy].keywords)

    def test_kodo_without_kindred_destroys_lowest_current_attack(self):
        g=self.game((KODO,),enemy=(SMALL,BIG));self.play(g,KODO)
        self.assertEqual([e.card_id for e in self.board(g,2)],[BIG])

    def test_kodo_kindred_uses_previous_closed_own_turn(self):
        g=self.game((SMALL,KODO),enemy=(WALL,BIG));self.play(g,SMALL);self.cycle(g);self.play(g,KODO)
        self.assertEqual([e.card_id for e in self.board(g,2)],[WALL]);self.portable(g)

    def test_kodo_different_previous_type_keeps_lowest_attack(self):
        g=self.game((BIG,KODO),enemy=(WALL,SMALL));self.play(g,BIG);self.cycle(g);self.play(g,KODO)
        self.assertEqual([e.card_id for e in self.board(g,2)],[SMALL])

    def test_kodo_empty_enemy_board_does_not_consume_rng(self):
        g=self.game((KODO,));before=g._rng.getstate();self.play(g,KODO);self.assertEqual(g._rng.getstate(),before)

    def test_opu_battlecry_casts_named_fan_once_without_combo(self):
        g=self.game((OPU,),enemy=(WALL,WALL));source=self.play(g,OPU)
        self.assertEqual([c.card_id for c in g.state.cast_history],[FAN])
        self.assertTrue(all(e.health==9 for e in self.board(g,2)))
        self.assertEqual(g.state.cast_history[0].caster_id,source);self.portable(g)

    def test_opu_active_combo_and_battlecry_are_independent_entries(self):
        g=self.game(('k47.noop',OPU),enemy=(WALL,));self.play(g,'k47.noop');self.play(g,OPU)
        self.assertEqual(sum(c.card_id==FAN for c in g.state.cast_history),2)
        self.assertEqual(self.board(g,2)[0].health,8);self.assertEqual(len(g.state.combo_history),1);self.portable(g)

    def test_opu_deathrattle_casts_a_separate_fan(self):
        g=self.game(('k47.kill',),board=(OPU,),enemy=(WALL,));self.play(g,'k47.kill',self.eid(g,OPU,'board'))
        self.assertEqual(sum(c.card_id==FAN for c in g.state.cast_history),1);self.assertEqual(self.board(g,2)[0].health,9)

    def test_opu_resolves_real_deaths_between_battlecry_and_combo(self):
        g=self.game(('k47.noop',OPU),enemy=('k47.seed',));self.play(g,'k47.noop');self.play(g,OPU)
        enemy=self.board(g,2);self.assertEqual(len(enemy),1);self.assertEqual((enemy[0].card_id,enemy[0].health),(SMALL,3))
        fans=[c for c in g.state.cast_history if c.card_id==FAN];self.assertEqual(len(fans),2)
        death=next(e for e in g.events if e.kind=='minion_died')
        starts=[e.sequence for e in g.events if e.kind=='spell_cast_started'and e.source_id in(c.source_id for c in fans)]
        self.assertLess(starts[0],death.sequence);self.assertLess(death.sequence,starts[1]);self.portable(g)

    def test_fan_named_dependency_damages_only_enemy_minions_then_draws(self):
        g=self.game((FAN,),board=(WALL,),enemy=(WALL,));source=self.play(g,FAN)
        self.assertEqual(self.board(g)[0].health,10);self.assertEqual(self.board(g,2)[0].health,9)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(len([d for d in g.state.draw_history if d.source_id==source]),1)

    def test_nablya_copies_only_damaged_friendly_minions_with_current_stats(self):
        g=self.game(('k47.grow','k47.hit3',NABLYA),board=(SMALL,WALL),enemy=(WALL,));original=self.eid(g,SMALL,'board')
        self.play(g,'k47.grow',original);self.play(g,'k47.hit3',original);self.play(g,NABLYA)
        copies=[e for e in self.board(g)if e.origin_entity_id==original];self.assertEqual(len(copies),1)
        copy=copies[0];self.assertEqual((copy.attack,copy.health,copy.max_health),(4,3,6))
        self.assertIn(Keyword.RUSH,copy.keywords);self.assertNotIn(Keyword.RUSH,g.state.entities[original].keywords);self.portable(g)

    def test_nablya_undamaged_or_enemy_minions_are_not_copied(self):
        g=self.game(('k47.ping',NABLYA),board=(SMALL,),enemy=(WALL,));self.play(g,'k47.ping',self.eid(g,WALL,'board',2))
        self.play(g,NABLYA);self.assertEqual([e.card_id for e in self.board(g)],[SMALL,NABLYA])

    def test_nablya_copy_wait_recovers_original_success_and_rush(self):
        g=self.game(('k47.ping',NABLYA),board=(SMALL,'k47.copy_wait'));original=self.eid(g,SMALL,'board')
        self.play(g,'k47.ping',original);self.play(g,NABLYA);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.choose(g);copies=[e for e in self.board(g)if e.origin_entity_id==original]
        self.assertEqual(len(copies),1);self.assertIn(Keyword.RUSH,copies[0].keywords);self.portable(g)

    def test_nablya_multiple_damaged_minions_each_produce_one_copy(self):
        g=self.game(('k47.ping','k47.ping',NABLYA),board=(SMALL,WALL))
        originals=[self.eid(g,cid,'board')for cid in(SMALL,WALL)]
        for eid in originals:self.play(g,'k47.ping',eid)
        self.play(g,NABLYA);copies=[e for e in self.board(g)if e.origin_entity_id in originals]
        self.assertEqual(len(copies),2);self.assertTrue(all(Keyword.RUSH in e.keywords for e in copies))

    def test_nablya_pending_second_copy_retains_typed_residence_through_recovery(self):
        g=self.game(('k47.ping','k47.ping',NABLYA),board=(SMALL,WALL,'k47.copy_wait'))
        originals=[self.eid(g,cid,'board')for cid in(SMALL,WALL)]
        for eid in originals:self.play(g,'k47.ping',eid)
        self.play(g,NABLYA);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        copies=[e for e in self.board(g)if e.origin_entity_id in originals]
        self.assertEqual(len(copies),2);self.assertTrue(all(Keyword.RUSH in e.keywords for e in copies));self.portable(g)

    def test_captured_copy_uses_current_material_from_original_residence(self):
        g=self.game(('k47.deferred',),board=(SMALL,));original=self.eid(g,SMALL,'board')
        self.play(g,'k47.deferred');g=self.portable(g);self.choose(g,'stay')
        copies=[e for e in self.board(g)if e.origin_entity_id==original];self.assertEqual(len(copies),1);self.portable(g)

    def test_captured_copy_does_not_rebind_after_same_entity_reenters(self):
        g=self.game(('k47.deferred',),board=(SMALL,));original=self.eid(g,SMALL,'board')
        before=g.state.entities[original].board_presence_id;self.play(g,'k47.deferred');g=self.portable(g);self.choose(g,'leave')
        self.assertEqual([e.id for e in self.board(g)],[original])
        self.assertNotEqual(g.state.entities[original].board_presence_id,before);self.portable(g)

    def test_captured_copy_rejects_future_and_unknown_residence(self):
        g=self.game(board=(SMALL,));s=g.state;original=self.eid(g,SMALL,'board')
        for ref in(BoardPresenceReference(original,s.next_order),BoardPresenceReference(s.next_entity_id,1)):
            with self.assertRaises(ValueError):CopyMinion(ref,1).validate_in_state(s)

    def test_nablya_full_board_neither_overfills_nor_grants_rush_to_original(self):
        g=self.game(('k47.ping',NABLYA),board=(SMALL,)*6);original=self.eid(g,SMALL,'board')
        self.play(g,'k47.ping',original);self.play(g,NABLYA)
        self.assertEqual(len(self.board(g)),7);self.assertNotIn(Keyword.RUSH,g.state.entities[original].keywords)

    def test_player_projection_hides_remaining_hand_and_deck(self):
        g=self.game((MARROW,),corpses=1,enemy_hand=(BIG,));self.play(g,MARROW)
        public=g.for_player(2).observe()['observation'];own=next(p for p in public['players']if p['id']==1)
        self.assertNotIn('resource_operations',public);self.assertTrue(all(set(c)=={'ref','card_id'}for c in own['hand']))
        self.assertNotIn(SMALL,json.dumps(own.get('deck',{})));self.portable(g)
