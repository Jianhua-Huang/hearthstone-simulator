"""Real actions over the complete declared seven-spell Protoss domain."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import protoss_spell_domain as native
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.card_conditions import UnknownCardFactError, matches_ability
from hs_sim.engine.costs import matches_cost_values, quote_cost, quote_generated_cost
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, GainArmor,
    GrantKeyword, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.model import CardAbilityCondition, CardMetadata, CostSpec, DamageKind, Rarity, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolMember, PoolQuery
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

HOT,CHRONO,CANNON,PYLON,HALLU,SHIELD,RESONANCE,BLINK=native.LEAVES
ZEALOT=native.TOKEN
P='k604.'
NOOP,FIRE,FROST,PROTO,PLAIN,UNKNOWN,CHIP,BUFF,SILENCE,CAST,REACT,KILLREACT,WAITCOPY,WAITDRAW,WAITDEATH,DOOM=(P+s for s in
    ('noop','fire','frost','proto','plain','unknown','chip','buff','silence','cast','react','killreact','waitcopy','waitdraw','waitdeath','doom'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context(mode='normal'):return GenerationContext(P+'complete-domain-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    r.register_behavior(NOOP,lambda c:())
    def fault(c):raise ResolutionError('K604 deliberate continuation failure')
    r.register_behavior(P+'fault',fault)
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'wait',wait)
    r.register_behavior(CHIP,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    r.register_behavior(BUFF,lambda c:(Buff(c.target_id,attack=2,health=2,source_id=c.source_id),))
    r.register_behavior(SILENCE,lambda c:(Silence(c.target_id),))
    r.register_behavior(CAST,lambda c:(CastSpell(c.player_id,FIRE,c.source_id),))
    for cid,school,factions in((NOOP,None,()),(FIRE,SpellSchool.FIRE,()),(FROST,SpellSchool.FROST,()),(PROTO,None,('protoss',))):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0 if cid==NOOP else 4,spell_school=school,
            on_play=P+'wait' if mode=='price_wait' and cid==FIRE else NOOP,
            metadata=replace(META,factions=factions)))
    for cid,body in((CHIP,CHIP),(BUFF,BUFF),(SILENCE,SILENCE)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=body,targeting=TargetSpec(),metadata=META))
    r.register_card(CardDefinition(CAST,CAST,CardType.SPELL,on_play=CAST,metadata=META))
    for cid,meta in((PLAIN,META),(UNKNOWN,replace(META,factions=None)),(DOOM,replace(META,factions=('protoss',)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=1,health=3 if cid==DOOM else 8,
            metadata=meta,deathrattle=P+'wait' if cid==DOOM else None))
    def reaction(c):
        e=c.event;target=c.state.entities.get(e.target_id)
        if c.source.card_id==REACT and e.kind=='health_resolved' and target is not None and target.kind==CardType.MINION:
            if e.source_id is not None and c.state.entities[e.source_id].card_id==CANNON and target.health>0:
                return (Destroy(target.id,c.source_id),)
        if c.source.card_id==KILLREACT and e.kind=='card_committed' and e.source_id is not None and c.state.entities[e.source_id].card_id==HALLU:
            ids=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ZEALOT]
            return tuple(Destroy(i,c.source_id)for i in ids)
        if c.source.card_id==WAITCOPY and e.kind=='minion_summoned' and target is not None and target.origin_entity_id is not None:
            return wait(c)
        if c.source.card_id==WAITDRAW and e.kind=='card_drawn' and e.source_id is not None and c.state.entities[e.source_id].card_id in(CHRONO,BLINK):
            return wait(c)
        return ()
    r.register_behavior(P+'react',reaction)
    for cid,event in((REACT,'health_resolved'),(KILLREACT,'card_committed'),(WAITCOPY,'minion_summoned'),(WAITDRAW,'card_drawn')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,metadata=META,triggers=(TriggerSpec(event,P+'react'),)))
    for cid in(NOOP,FIRE,FROST,PROTO,PLAIN,UNKNOWN,DOOM):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    pool=native.local_pool(r,context(mode))
    if mode=='unknown':
        missing=P+'unknown_proto_spell';r.register_pool_card(PoolCard(missing,CardType.SPELL,3,replace(META,factions=('protoss',))))
        pool=replace(pool,members=pool.members+(PoolMember(missing),))
    r.register_pool(pool);r.validate();return r


class ProtossSpellDomainTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,deck=(NOOP,)*5,board=(),enemy_board=(),player=1,mode='normal'):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else (),deck=deck if p==player else(NOOP,)*5,
            board=board if p==player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=604,generation_context=context(mode)),registry(mode))

    def paid(self,g,cid,target=None,player=1):
        entity=self.entity(g,cid,player);amount=quote_cost(g.state,g.registry,entity).amount;mana=g.state.players[player].mana
        source=self.play(g,cid,target,player);self.assertEqual(g.state.players[player].mana,mana-amount)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,amount));return source

    def cost(self,g,cid,player=1):return quote_cost(g.state,g.registry,self.entity(g,cid,player)).amount

    def test_nine_full_records_eighteen_primary_faces_exact_seven_candidates_and_real_roles(self):
        data=native.load_batch();rows={r['record']['id']:r for r in data['dependencies']}
        self.assertEqual((len(rows),len(data['official_observations'])),(9,18))
        for obs in data['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
        self.assertEqual(tuple(data['candidate_ids']),native.CANDIDATES)
        self.assertEqual((registry().card(HOT).cost,registry().card(PYLON).cost),(0,0))
        self.assertEqual((registry().card(ZEALOT).cost,registry().card(ZEALOT).attack,registry().card(ZEALOT).health),(3,3,4))
        self.assertFalse(registry().card(ZEALOT).metadata.collectible)
        self.assertEqual(registry().card(CHRONO).metadata.classes,(CardClass.DRUID,CardClass.MAGE,CardClass.PRIEST,CardClass.ROGUE))
        pool=registry().pool(native.POOL,context());self.assertTrue(pool.complete)
        self.assertEqual(tuple((m.card_id,m.weight)for m in pool.members),tuple((c,1)for c in native.CANDIDATES))
        self.assertIn(RESONANCE,native.CANDIDATES);self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_hot_streak_only_next_fire_matches_physical_generated_dto_and_real_payment_both_seats(self):
        for p in(1,2):
            g=self.game((HOT,FIRE,FIRE,FROST,PROTO,PLAIN),player=p);self.paid(g,HOT,player=p)
            self.assertEqual((self.cost(g,FIRE,p),self.cost(g,FROST,p),self.cost(g,PROTO,p),self.cost(g,PLAIN,p)),(2,4,4,4))
            self.assertEqual(quote_generated_cost(g.state,g.registry,p,FIRE).amount,2)
            self.assertEqual(len(g.state.players[p].cost_modifiers),1)
            view=g.for_player(p).observe()['observation'];shown={x['card_id']:x['cost']['amount'] for x in view['players'][p-1]['hand']}
            self.assertEqual((shown[FIRE],shown[FROST],shown[PROTO],shown[PLAIN]),(2,4,4,4))
            self.paid(g,FROST,player=p);self.assertEqual(self.cost(g,FIRE,p),2)
            self.paid(g,FIRE,player=p);self.assertEqual(self.cost(g,FIRE,p),4)

    def test_pylon_matches_next_protoss_card_not_ordinary_card_or_enemy_and_zero_cost_consumes(self):
        g=self.game((PYLON,NOOP,ZEALOT,PROTO));self.paid(g,PYLON)
        self.assertEqual((self.cost(g,ZEALOT),self.cost(g,PROTO)),(1,2))
        self.assertEqual(quote_generated_cost(g.state,g.registry,2,ZEALOT).amount,3)
        self.paid(g,NOOP);self.assertEqual(self.cost(g,ZEALOT),1)
        self.paid(g,ZEALOT);self.assertEqual(self.cost(g,PROTO),4)
        g=self.game((PYLON,PYLON,PROTO));self.paid(g,PYLON);self.paid(g,PYLON)
        self.assertEqual(self.cost(g,PROTO),2);self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_shield_battery_armor_and_next_protoss_spell_persist_until_use(self):
        g=self.game((SHIELD,ZEALOT,PROTO,PROTO,FIRE));self.paid(g,SHIELD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual((self.cost(g,ZEALOT),self.cost(g,FIRE),self.cost(g,PROTO)),(3,4,2))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.cost(g,PROTO),2)
        self.paid(g,ZEALOT);self.assertEqual(self.cost(g,PROTO),2)
        self.paid(g,PROTO);self.assertEqual(self.cost(g,PROTO),4);self.portable(g)

    def test_turn_limited_school_and_faction_prices_expire(self):
        for card,match in((HOT,FIRE),(PYLON,ZEALOT)):
            g=self.game((card,match));self.paid(g,card);self.assertEqual(self.cost(g,match),g.registry.card(match).cost-2)
            g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.cost(g,match),g.registry.card(match).cost)

    def test_automatic_fire_cast_does_not_pay_or_consume_original_one_use_quote(self):
        g=self.game((HOT,CAST,FIRE));self.paid(g,HOT);self.paid(g,CAST)
        self.assertEqual(self.cost(g,FIRE),2);self.assertEqual(len(g.state.cast_history),3)

    def test_public_action_submission_uses_native_printed_price_and_consumes_only_original_use(self):
        g=self.game((HOT,FIRE,FIRE));self.paid(g,HOT)
        port=g.for_player(1);listing=port.legal_actions()
        self.assertEqual(listing['observation']['players'][0]['hand'][0]['cost']['amount'],2)
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(28,FIRE,2))
        self.assertEqual(self.cost(g,FIRE),4)

    def test_active_native_price_and_spent_original_payment_restore_through_real_payload_wait(self):
        g=self.game((HOT,FIRE,FROST),mode='price_wait');self.paid(g,HOT);self.portable(g)
        self.paid(g,FIRE);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana,28);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(g.state.players[1].cost_modifiers),0);self.assertEqual(self.cost(g,FROST),4)

    def test_native_printed_conditions_unknown_faction_fails_explicitly_no_negative_current_aliases(self):
        for name in('fire_spell','protoss'):
            for kwargs in({'basis':'current'},{'basis':'printed','present':False}):
                with self.assertRaises(ValueError):CardAbilityCondition(name,**kwargs)
        d=registry().card(ZEALOT);self.assertTrue(matches_ability(native.PROTOSS,d))
        self.assertTrue(matches_cost_values(CostSpec(ability=native.PROTOSS),d,False,abilities=()))
        with self.assertRaises(UnknownCardFactError):matches_ability(native.PROTOSS,registry().card(UNKNOWN))
        g=self.game((PYLON,UNKNOWN));self.paid(g,PYLON)
        with self.assertRaises(UnknownCardFactError):self.cost(g,UNKNOWN)

    def test_chrono_draws_two_actual_matching_cards_then_named_charge_zealot_both_seats(self):
        for p in(1,2):
            g=self.game((CHRONO,),deck=(FROST,PROTO,ZEALOT,NOOP),player=p);self.paid(g,CHRONO,player=p)
            hand=[g.state.entities[i].card_id for i in g.state.players[p].hand];self.assertCountEqual(hand,[PROTO,ZEALOT])
            board=[g.state.entities[i]for i in g.state.players[p].board];self.assertEqual(len(board),1)
            self.assertEqual((board[0].card_id,board[0].attack,board[0].health),(ZEALOT,3,4));self.assertIn(Keyword.CHARGE,board[0].keywords)
            self.assertCountEqual([g.state.entities[i].card_id for i in g.state.players[p].deck],[FROST,NOOP])

    def test_chrono_empty_matching_deck_does_not_fatigue_and_full_board_still_draws(self):
        g=self.game((CHRONO,),deck=());rng=g.snapshot()['rng_state'];self.paid(g,CHRONO)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        g=self.game((CHRONO,),deck=(PROTO,ZEALOT),board=(PLAIN,)*7);self.paid(g,CHRONO)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.players[1].hand),2)

    def test_chrono_draw_waits_restore_replay_and_original_order_before_summon(self):
        g=self.game((CHRONO,),deck=(PROTO,ZEALOT),board=(WAITDRAW,));self.paid(g,CHRONO)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].board),1)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for obj in(g,other):self.choose(obj);self.assertIsNotNone(obj.state.pending_choice);self.choose(obj)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].board),2)

    def test_blink_original_combo_reduces_actual_drawn_protoss_minion_not_spell(self):
        for combo in(False,True):
            g=self.game((NOOP,BLINK),deck=(PROTO,ZEALOT,PLAIN))
            if combo:self.paid(g,NOOP)
            self.paid(g,BLINK);self.assertEqual(self.cost(g,ZEALOT),1 if combo else 3)
            self.assertCountEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[PROTO,PLAIN])

    def test_blink_waiting_original_arrival_receives_permanent_local_price_after_reactions(self):
        g=self.game((NOOP,BLINK),deck=(ZEALOT,),board=(WAITDRAW,));self.paid(g,NOOP);self.paid(g,BLINK)
        other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cost(g,ZEALOT),1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.cost(g,ZEALOT),1)

    def test_photon_cannon_actual_kill_grants_permanent_stackable_minion_only_discount(self):
        g=self.game((CANNON,CANNON,ZEALOT,PROTO),enemy_board=(DOOM,DOOM))
        for _ in range(2):
            target=next(i for i in g.state.players[2].board if g.state.entities[i].card_id==DOOM)
            self.paid(g,CANNON,target);self.choose(g)
        self.assertEqual((self.cost(g,ZEALOT),self.cost(g,PROTO)),(1,4))
        self.paid(g,ZEALOT);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(quote_generated_cost(g.state,g.registry,1,ZEALOT).amount,1)

    def test_photon_nonlethal_reaction_destroy_and_hero_damage_do_not_forge_its_kill(self):
        g=self.game((CANNON,ZEALOT),enemy_board=(PLAIN,),board=(REACT,));target=g.state.players[2].board[0]
        self.paid(g,CANNON,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(self.cost(g,ZEALOT),3)
        g=self.game((CANNON,ZEALOT));self.paid(g,CANNON,g.state.players[2].hero_id);self.assertEqual(self.cost(g,ZEALOT),3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)

    def test_photon_death_waits_exact_result_restore_replay_and_failure_preserve_payment(self):
        g=self.game((CANNON,ZEALOT),enemy_board=(DOOM,));self.paid(g,CANNON,g.state.players[2].board[0]);self.assertEqual(self.cost(g,ZEALOT),3)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.cost(g,ZEALOT),2)

    def test_hallucination_target_is_public_friendly_protoss_and_copy_preserves_current_stats(self):
        g=self.game((BUFF,HALLU,CHIP,CHIP),board=(ZEALOT,PLAIN),enemy_board=(ZEALOT,))
        original=g.state.players[1].board[0];self.paid(g,BUFF,original)
        for target in(g.state.players[1].board[1],g.state.players[2].board[0],g.state.players[1].hero_id):
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,HALLU,target)
            self.assertEqual(g.snapshot(),saved)
        self.paid(g,HALLU,original);copy=g.state.players[1].board[-1]
        self.assertEqual((g.state.entities[copy].attack,g.state.entities[copy].health,g.state.entities[copy].origin_entity_id),(5,6,original))
        self.paid(g,CHIP,copy);self.paid(g,CHIP,original)
        self.assertEqual((g.state.entities[copy].health,g.state.entities[original].health),(4,5))

    def test_hallucination_double_damage_is_silenceable_and_full_board_does_not_modify_original(self):
        g=self.game((HALLU,SILENCE,CHIP),board=(ZEALOT,));original=g.state.players[1].board[0];self.paid(g,HALLU,original)
        copy=g.state.players[1].board[-1];self.paid(g,SILENCE,copy);self.paid(g,CHIP,copy);self.assertEqual(g.state.entities[copy].health,3)
        g=self.game((HALLU,CHIP),board=(ZEALOT,)+(PLAIN,)*6);original=g.state.players[1].board[0]
        self.paid(g,HALLU,original);self.paid(g,CHIP,original);self.assertEqual(g.state.entities[original].health,3)

    def test_hallucination_copy_wait_retains_original_followup_restore_replay_and_rollback(self):
        g=self.game((HALLU,CHIP),board=(ZEALOT,WAITCOPY));original=g.state.players[1].board[0];self.paid(g,HALLU,original)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        copy=g.state.players[1].board[-1];self.paid(g,CHIP,copy);self.assertEqual(g.state.entities[copy].health,2)

    def test_hallucination_original_target_dying_before_body_keeps_paid_play(self):
        g=self.game((HALLU,),board=(ZEALOT,KILLREACT));target=g.state.players[1].board[0]
        self.paid(g,HALLU,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(g.state.players[1].mana,29)

    def test_resonance_real_damage_then_complete_seven_member_domain_and_unknown_member_rollback(self):
        g=self.game((RESONANCE,),enemy_board=(PLAIN,));target=g.state.players[2].board[0];source=self.paid(g,RESONANCE,target)
        self.assertEqual(g.state.entities[target].health,3);self.assertEqual(len(g.state.players[1].hand),1)
        made=g.state.entities[g.state.players[1].hand[0]];self.assertIn(made.card_id,native.CANDIDATES)
        self.assertTrue(any(e.kind=='card_created' and e.source_id==source and e.target_id==made.id for e in g.events))
        g=self.game((RESONANCE,),enemy_board=(PLAIN,),mode='unknown');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'[Uu]nsupported|[Mm]issing|executable'):self.play(g,RESONANCE,g.state.players[2].board[0])
        self.assertEqual(g.snapshot(),saved)

    def test_complete_local_host_pool_bound_without_extending_standard_roots_or_ordinary_inventory(self):
        from hs_sim.local_pool_format import build_cn37_local_pool_format
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        fmt=build_cn37_local_pool_format();old=build_cn37_launch_candidate_format();pool=fmt.registry.pool(native.POOL,fmt.context)
        self.assertEqual(tuple(m.card_id for m in pool.members),native.CANDIDATES);self.assertTrue(pool.complete)
        self.assertEqual(fmt.root_card_ids,old.root_card_ids);self.assertFalse(fmt.formal_pool_complete)
        for pool_id in('constructed.cards','constructed.minions'):
            self.assertEqual(fmt.registry.pool(pool_id,fmt.context).members,old.registry.pool(pool_id,old.context).members)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(RESONANCE,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(ZEALOT,))),generation_context=fmt.context),fmt.registry)
        self.paid(g,RESONANCE,g.state.players[2].board[0]);self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,native.CANDIDATES)

    def test_bad_final_dependency_metadata_rejected_before_any_card_or_behavior_is_registered(self):
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['health']=9
        r=batch.registration_prefix(build_registry,'hs_sim.cards.protoss_spell_domain.register_protoss_spell_domain',native.register_protoss_spell_domain)
        before=(dict(r.cards),dict(r._behaviors),dict(r.pool_cards),dict(r._target_rules))
        with patch.object(native,'load_batch',return_value=data):
            with self.assertRaises(TargetValidationError):native.register_protoss_spell_domain(r)
        self.assertEqual((r.cards,r._behaviors,r.pool_cards,r._target_rules),before)


if __name__=='__main__':unittest.main()
