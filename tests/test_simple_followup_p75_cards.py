"""Actual turn/paid histories, generated costs and original damaged characters."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p75_cards as cards
from hs_sim.cards.simple_followup_p75_cards import (WANNABE,JADE,DRILLS,STALKS,WINGS,ROOTS,
    PREFIX,POOL_ID,load_batch,register_simple_followup_p75_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,
    IllegalAction,Keyword,PaymentType,PlayerSetup,PlayCard,Rarity,Registry,Scenario,SelectChoice,
    TargetSpec,UseHandAction,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,Heal,
    InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,MoveCard

TEST='p75.test.'
HERO,HP,FILLER,MECH,SHIELD,POWER,WATCH=(TEST+i for i in('hero','power','filler','mech','shield','spellpower','watch'))
PAID2,PRINTED5,ONE2,HEALTH2,REPEAT2,QUOTES,FREE,KILL,BOUNCE,SILENCE,STEAL,SHOT,HEAL=(TEST+i for i in
    ('paid2','printed5','one2','health2','repeat2','quotes','free','kill','bounce','silence','steal','shot','heal'))
A,B,WRONG,SPELL8,UNKNOWN=(TEST+i for i in('eight-a','eight-b','wrong-five','eight-spell','unknown-eight'))
CONTEXT=GenerationContext(TEST,'experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=(),collectible=True,cls=CardClass.NEUTRAL):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p75_cards(r)
    elif not all(present):raise AssertionError('P75 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=Registry('p75-small-native-fixtures');register_simple_followup_p75_cards(r)
    r.register_behavior(TEST+'nop',lambda c:())
    r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=TEST+'nop',metadata=meta(collectible=False,cls=CardClass.ROGUE)))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(collectible=False,cls=CardClass.ROGUE)))
    for cid,cost,atk,hp,kw in((FILLER,0,0,30,()),(MECH,2,2,30,()),(SHIELD,1,2,20,(Keyword.DIVINE_SHIELD,)),
            (A,8,5,10,()),(B,8,1,5,()),(WRONG,5,1,3,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,keywords=kw,metadata=meta()))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=30,spell_damage=3,metadata=meta()))
    def fail(c):raise ResolutionError('P75 deliberate continuation failure')
    def reenter(c):
        target=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(target),target.controller),)
    def quotes(c):
        operations={PRINTED5:CostSpec(set_to=2),ONE2:CostSpec(set_to=1),HEALTH2:CostSpec(payment=PaymentType.HEALTH)}
        return tuple(ModifyCost(i,operations[c.state.entities[i].card_id])for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in operations)
    def shot(c):
        source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id in WINGS)
        return(Damage(c.target_id,1,source,DamageKind.MINION_ABILITY),)
    def heal(c):
        source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id in WINGS)
        return(Heal(c.target_id,1,source),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    bodies={PAID2:lambda c:(),PRINTED5:lambda c:(),ONE2:lambda c:(),HEALTH2:lambda c:(),
        REPEAT2:lambda c:(AddToHand(c.player_id,REPEAT2,c.source_id),),QUOTES:quotes,FREE:lambda c:(),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        SILENCE:lambda c:(Silence(c.target_id),),STEAL:lambda c:(ChangeControl(c.target_id,2),),SHOT:shot,HEAL:heal,SPELL8:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            cost=2 if cid in(PAID2,ONE2,HEALTH2,REPEAT2)else 5 if cid==PRINTED5 else 8 if cid==SPELL8 else 0,
            targeting=TargetSpec()if cid in(KILL,BOUNCE,SILENCE,STEAL,SHOT,HEAL)else None,metadata=meta()))
    members=[A,B,WRONG,SPELL8]
    if mode=='unknown':r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,8,meta()));members.append(UNKNOWN)
    for cid in(A,B,WRONG,SPELL8):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID,'p75-fixture',TEST,'experimental',tuple(PoolMember(i)for i in members)))
    if mode in('combo','generated','wing'):
        event='combo_started'if mode=='combo'else'card_created'if mode=='generated'else'health_resolved'
        def eligible(c):
            if mode=='combo':return c.state.entities[c.event.source_id].card_id==WANNABE
            if mode=='generated':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==JADE
            result=c.health_result
            return result is not None and result.source_card_id in WINGS and result.damage_dealt>0
        def watcher(c):
            if mode=='combo':
                target=c.event.source_id;effects=(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))
            elif mode=='generated':
                effects=(MoveCard(CardReference.capture(c.state.entities[c.event.target_id]),1,Zone.DECK,'top'),)
            else:
                target=c.health_result.target_id;effects=(ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original residency',effects),
                ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'pause',watcher)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'pause',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP75Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode=None,enemy_hand=()):
        self.mode=mode
        if mode=='wing':board=(WATCH,)+board
        elif mode in('combo','generated'):enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP),
            PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP)),seed=7575,generation_context=CONTEXT),fixture_registry(mode,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def generated(self,g,zone='hand'):
        return[g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id in(A,B)]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry)
        self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',visible)
    def rollback(self,g):
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)

    def test_a0_wannabe_first_play_has_no_combo_and_no_future_growth_listener(self):
        g=self.game((WANNABE,FREE));source=self.play(g,WANNABE);self.play(g,FREE)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,2))
        self.assertFalse(g.state.combo_history);self.assertEqual(g.state.players[1].mana,46);self.portable(g)

    def test_a1_two_wannabes_use_original_other_play_occurrences_and_gain_once_each(self):
        g=self.game((FREE,WANNABE,WANNABE,FREE));self.play(g,FREE);first=self.play(g,WANNABE);second=self.play(g,WANNABE);self.play(g,FREE)
        self.assertEqual((g.state.entities[first].attack,g.state.entities[first].health),(3,3))
        self.assertEqual((g.state.entities[second].attack,g.state.entities[second].health),(4,4))
        self.assertEqual(len(g.state.combo_history),2);self.assertEqual(len(g.state.play_history),4);self.portable(g)

    def test_a2_previous_turn_and_opponent_plays_do_not_enable_current_combo(self):
        g=self.game((FREE,WANNABE),enemy_hand=(PAID2,));self.play(g,FREE);g.apply(EndTurn(1));self.play(g,PAID2,pid=2);g.apply(EndTurn(2))
        source=self.play(g,WANNABE);self.assertEqual(g.state.entities[source].attack,2);self.assertFalse(g.state.combo_history);self.portable(g)

    def test_a3_actual_prepare_investment_and_turn_lock_are_separate_from_card_play_counter(self):
        g=self.game((WANNABE,PAID2));source=self.first(g,WANNABE).id;g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual((g.state.players[1].mana,g.state.entities[source].cost),(47,0));self.assertFalse(g.state.play_history)
        with self.assertRaises(IllegalAction):self.play(g,WANNABE)
        self.next_own(g);self.play(g,PAID2);self.play(g,WANNABE)
        self.assertEqual(g.state.entities[source].attack,3);self.assertEqual(g.state.play_history[-1].cost,0);self.portable(g)

    def test_a4_pending_combo_wait_restores_failed_choice_and_does_not_buff_same_id_reentry(self):
        g=self.game((FREE,WANNABE),mode='combo');self.play(g,FREE);source=self.play(g,WANNABE)
        self.rollback(g);self.choose(g,'change');self.assertIn(source,g.state.players[1].board)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,2))
        self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_b0_jade_exact_printed_eight_minion_pool_and_zero_history_cost(self):
        g=self.game((JADE,));source=self.play(g,JADE);results=self.generated(g)
        self.assertEqual(len(results),2);self.assertTrue(all(e.cost==8 for e in results));self.assertEqual(g.state.players[1].mana,45)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.play_history[0].source_id,source);self.portable(g)

    def test_b1_jade_uses_actual_two_mana_not_printed_cost_health_or_hero_power(self):
        g=self.game((QUOTES,PAID2,PRINTED5,ONE2,HEALTH2,JADE));self.play(g,QUOTES)
        for cid in(PAID2,PRINTED5,ONE2,HEALTH2):self.play(g,cid)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g,JADE)
        self.assertEqual([e.cost for e in self.generated(g)],[6,6]);self.assertEqual(g.state.players[1].mana,38)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        self.assertEqual([(r.cost,r.payment)for r in g.state.play_history[1:5]],[(2,PaymentType.MANA),(2,PaymentType.MANA),(1,PaymentType.MANA),(2,PaymentType.HEALTH)]);self.portable(g)

    def test_b2_repeated_real_two_mana_plays_are_distinct_occurrences_and_generated_cost_floors_zero(self):
        g=self.game((REPEAT2,JADE))
        for _ in range(9):self.play(g,REPEAT2)
        self.play(g,JADE);self.assertEqual([e.cost for e in self.generated(g)],[0,0])
        self.assertEqual(len(g.state.play_history),10);self.assertEqual(g.state.players[1].mana,27);self.portable(g)

    def test_b3_opponent_payments_do_not_reduce_own_generated_cards(self):
        g=self.game((JADE,),enemy_hand=(PAID2,));g.apply(EndTurn(1));self.play(g,PAID2,pid=2);g.apply(EndTurn(2));self.play(g,JADE)
        self.assertEqual([e.cost for e in self.generated(g)],[8,8]);self.portable(g)

    def test_b4_generated_first_delivery_wait_preserves_cost_batch_and_original_payment(self):
        g=self.game((PAID2,JADE),mode='generated');self.play(g,PAID2);self.play(g,JADE)
        self.assertEqual([e.cost for e in self.generated(g)],[7]);rng=g.snapshot()['rng_state'];self.rollback(g);self.choose(g,'change')
        self.assertEqual([e.cost for e in self.generated(g)],[7]);self.assertEqual([e.cost for e in self.generated(g,'deck')],[7])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,43);self.portable(g)

    def test_b5_full_hand_burn_and_eligible_unknown_candidate_are_not_filtered(self):
        g=self.game((JADE,)+(FREE,)*9);self.play(g,JADE)
        self.assertEqual(len(self.generated(g)),1);self.assertEqual(sum(e.kind=='card_burned'for e in g.events),1);self.portable(g)
        g=self.game((JADE,)+(FREE,)*9,mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,JADE)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_c0_both_drills_native_rush_damage_and_single_attack_limit(self):
        for cid in DRILLS:
            g=self.game((cid,),enemy=(MECH,));source=self.play(g,cid);target=self.first(g,MECH,'board',2).id
            with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
            g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[source].health,1)
            with self.assertRaises(IllegalAction):g.apply(Attack(1,source,target))
            self.portable(g)

    def test_c1_all_four_stalks_only_own_end_and_printed_damage_ignores_spell_damage(self):
        g=self.game(board=STALKS+(POWER,));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22);self.portable(g)

    def test_c2_stalk_control_silence_and_death_use_native_lifetime(self):
        g=self.game((STEAL,),board=(STALKS[0],));source=self.first(g,STALKS[0],'board').id;self.play(g,STEAL,source)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)
        g=self.game((SILENCE,KILL),board=(STALKS[0],STALKS[1]));self.play(g,SILENCE,self.first(g,STALKS[0],'board').id)
        self.play(g,KILL,self.first(g,STALKS[1],'board').id);g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.portable(g)

    def test_d0_both_wings_freeze_after_real_positive_damage_even_when_source_dies(self):
        for cid in WINGS:
            g=self.game((cid,),enemy=(MECH,));source=self.play(g,cid);target=self.first(g,MECH,'board',2).id
            g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            self.assertTrue(g.state.entities[target].frozen);self.assertEqual(g.state.entities[target].health,28);self.portable(g)

    def test_d1_wing_freezes_actual_enemy_hero_and_friendly_damaged_character(self):
        g=self.game(board=(WINGS[0],));g.apply(Attack(1,self.first(g,WINGS[0],'board').id,g.state.players[2].hero_id))
        self.assertTrue(g.state.entities[g.state.players[2].hero_id].frozen);self.portable(g)
        g=self.game((SHOT,),board=(WINGS[1],FILLER));target=self.first(g,FILLER,'board').id;self.play(g,SHOT,target)
        self.assertTrue(g.state.entities[target].frozen);self.portable(g)

    def test_d2_shield_zero_damage_and_unrelated_attacker_or_healing_do_not_freeze(self):
        g=self.game((WINGS[0],),enemy=(SHIELD,));source=self.play(g,WINGS[0]);target=self.first(g,SHIELD,'board',2).id
        g.apply(Attack(1,source,target));self.assertFalse(g.state.entities[target].frozen);self.portable(g)
        g=self.game((HEAL,),board=(WINGS[0],MECH),enemy=(MECH,));target=self.first(g,MECH,'board',2).id
        self.play(g,HEAL,target);g.apply(Attack(1,self.first(g,MECH,'board').id,target));self.assertFalse(g.state.entities[target].frozen);self.portable(g)

    def test_d3_silenced_wing_loses_damage_freeze_trigger(self):
        g=self.game((SILENCE,),board=(WINGS[0],),enemy=(MECH,));source=self.first(g,WINGS[0],'board').id;target=self.first(g,MECH,'board',2).id
        self.play(g,SILENCE,source);g.apply(Attack(1,source,target));self.assertFalse(g.state.entities[target].frozen);self.portable(g)

    def test_d4_waiting_damage_result_does_not_freeze_new_same_id_target_after_reentry(self):
        g=self.game((WINGS[0],),enemy=(MECH,),mode='wing');source=self.play(g,WINGS[0]);target=self.first(g,MECH,'board',2).id
        g.apply(Attack(1,source,target));self.assertFalse(g.state.entities[target].frozen);self.rollback(g);self.choose(g,'change')
        self.assertIn(target,g.state.players[2].board);self.assertFalse(g.state.entities[target].frozen)
        self.assertEqual(g.state.entities[target].health,30);self.portable(g)

    def test_z0_complete_sources_actual_new_ids_and_old_assembled_content_are_preserved(self):
        from dataclasses import asdict
        from tools.card_batch import check_face
        from hs_sim.targets import canonical_digest
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(2,8,38))
        rows={x['record']['id']:x['record']for k in('cards','dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id'],{}))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        for cid,pin in d['already_present_fallback_definitions'].items():self.assertEqual(canonical_digest(asdict(after.card(cid))),pin['sha256'])
        for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
        for cid in d['unsupported_source_cards']:self.assertEqual(cid in before.cards,cid in after.cards)


if __name__=='__main__':unittest.main()
