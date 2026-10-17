"""Actual attack rewards, printed hand upgrades and necessary original Mech bodies."""
from dataclasses import asdict
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p73_cards as cards
from hs_sim.cards.simple_followup_p73_cards import (GRYPHON,CORRUPTED,TROUPE,LEVIATHAN,CLAW,
    MOON,SUNKEN,HELLBAT,NOBLE,MUSCLE,FORGED,ANNOY,ROOTS,PREFIX,load_batch,register_simple_followup_p73_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,
    Keyword,PlayerSetup,PlayCard,Rarity,Registry,Scenario,SelectChoice,TargetSpec,UseHandAction,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption,Destroy,Draw,InvokeBehavior,ModifyCost,RequestChoice,
    ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import LimitedTriggerSpec,SummonQuantitySpec
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,MoveCard

TEST='p73.test.'
HERO,HP,MECH,ALL,BEAST,DOUBLE,WATCH=(TEST+i for i in('hero','power','mech','all','beast','double','watch'))
KILL,BOUNCE,SILENCE,DRAW,BUFF,LOWER,HIGH,EQUAL,WAIT,SUMMON=(TEST+i for i in
    ('kill','bounce','silence','draw','buff','lower','high','equal','wait','summon'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=(),collectible=True,cls=CardClass.NEUTRAL):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,tribes=tribes)


@lru_cache(maxsize=1)
def original_annoy():
    return build_registry().card(ANNOY)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p73_cards(r)
    elif not all(present):raise AssertionError('P73 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=Registry('p73-small-native-fixtures');r.register_card(original_annoy());register_simple_followup_p73_cards(r)
    r.register_behavior(TEST+'nop',lambda c:())
    r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=TEST+'nop',metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(collectible=False,cls=CardClass.PALADIN)))
    for cid,atk,hp,tribes in((MECH,1,3,('mech',)),(ALL,1,4,('all',)),(BEAST,2,30,('beast',))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=atk,health=hp,metadata=meta(tribes)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    def fail(c):raise ResolutionError('P73 deliberate continuation failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1),)
    def back(c):return(MoveCard(CardReference.capture(c.state.entities[c.target_id]),1,Zone.HAND),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'back',back)
    def pause(c,effects=()):
        return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original residency',effects),
            ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
    def buff(c):return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),1,2,c.source_id)
        for i in c.state.players[1].hand if c.state.entities[i].kind==CardType.MINION)
    def lower(c):return(ModifyCost(next(i for i in c.state.players[1].hand if c.state.entities[i].card_id==GRYPHON),CostSpec(set_to=3)),)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        SILENCE:lambda c:(Silence(c.target_id),),DRAW:lambda c:(Draw(1,3,c.source_id),),BUFF:buff,LOWER:lower,
        HIGH:lambda c:(),EQUAL:lambda c:(),WAIT:pause,
        SUMMON:lambda c:(SummonByCard(1,(SummonEntryMaterial(LEVIATHAN),),cards.SummonCause.capture(c)),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            cost=6 if cid in(HIGH,WAIT)else 5 if cid==EQUAL else 0,
            targeting=TargetSpec()if cid in(KILL,BOUNCE,SILENCE)else None,metadata=meta()))
    if mode:
        event={'troupe':'minion_summoned','dredge':'card_dredged','sunken':'battlecry_started',
            'attack':'damage_dealt','forge':'card_forged','buff':'stored_card_buffed'}[mode]
        def eligible(c):
            target=c.state.entities.get(c.event.target_id)
            if mode=='attack':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==NOBLE
            if mode=='sunken':return c.state.entities[c.event.source_id].card_id==SUNKEN
            if target is None or target.controller!=1:return False
            if mode=='troupe':return target.card_id==ANNOY
            return mode in('dredge','forge')or target.card_id==MECH
        def watcher(c):
            effects=()
            if mode=='troupe':
                source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==DOUBLE)
                effects=(RemoveFromGame((MinionReference.capture(c.state.entities[source]),),c.source_id),)
            elif mode=='dredge':effects=(MoveCard(CardReference.capture(c.state.entities[c.event.target_id]),1,Zone.HAND),)
            elif mode in('sunken','attack'):
                source=c.event.source_id
                effects=(ReturnToHand(source),InvokeBehavior(TEST+'reenter',c.source_id,1,source))
            elif mode=='buff':
                target=next(i for i in c.state.players[1].hand if c.state.entities[i].card_id==ALL)
                effects=(MoveCard(CardReference.capture(c.state.entities[target]),1,Zone.DECK,'top'),InvokeBehavior(TEST+'back',c.source_id,1,target))
            return pause(c,effects)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'pause',watcher)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'pause',condition_id=TEST+'eligible'),),metadata=meta()))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP73Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(HIGH,MECH,ALL,BEAST),mode=None,seed=7373):
        self.mode=mode
        if mode:enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup(HERO,board=enemy,deck=(BEAST,)*12,mana=50,max_mana=50,mana_cap=50)),seed=seed),
            fixture_registry(mode,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def play(self,g,cid,target=None,position=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target_id=target,position=(len(g.state.players[1].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def dredge(self,g,cid):
        q=g.state.pending_choice;self.assertIsNotNone(q)
        self.choose(g,next(o.id for o in q.options if o.card_id==cid))
    def portable(self,g):
        reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry)
        self.assertEqual(reader.fingerprint(),g.registry.fingerprint())
        snap=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):
                self.assertNotIn('"'+key+'"',visible)
    def rollback(self,g):
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)

    def test_a0_gryphon_equal_cost_does_not_corrupt_then_higher_play_changes_same_entity(self):
        g=self.game((GRYPHON,EQUAL,HIGH));source=self.first(g,GRYPHON).id
        self.play(g,EQUAL);self.assertEqual(g.state.entities[source].card_id,GRYPHON);self.play(g,HIGH)
        e=g.state.entities[source];self.assertEqual((e.card_id,e.attack,e.health),(CORRUPTED,8,8))
        self.assertTrue({Keyword.CORRUPTED,Keyword.DIVINE_SHIELD,Keyword.TAUNT}<=set(e.keywords))
        self.assertEqual(len(g.state.play_history),2);self.assertEqual(g.state.players[1].mana,39);self.portable(g)

    def test_a1_corrupt_uses_local_quote_and_preserves_existing_numeric_attachments(self):
        g=self.game((GRYPHON,BUFF,LOWER,EQUAL));source=self.first(g,GRYPHON).id
        self.play(g,BUFF);self.play(g,LOWER);self.play(g,EQUAL);e=g.state.entities[source]
        self.assertEqual((e.card_id,e.attack,e.health,e.cost),(CORRUPTED,9,10,3));self.portable(g)

    def test_a2_higher_play_wait_keeps_corrupt_pending_and_failure_restores_one_paid_root(self):
        g=self.game((GRYPHON,WAIT));source=self.first(g,GRYPHON).id;self.play(g,WAIT)
        self.assertEqual(g.state.entities[source].card_id,GRYPHON);self.assertEqual(g.state.players[1].mana,44)
        self.rollback(g);self.choose(g);self.assertEqual(g.state.entities[source].card_id,CORRUPTED)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,44);self.portable(g)

    def test_b0_troupe_natural_death_uses_original_slot_and_exact_existing_annoy_definition(self):
        g=self.game((KILL,),board=(MECH,TROUPE,ALL));source=self.first(g,TROUPE,'board').id;self.play(g,KILL,source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[MECH,ANNOY,ANNOY,ANNOY,ALL])
        for i in g.state.players[1].board[1:4]:
            e=g.state.entities[i];self.assertEqual((e.attack,e.health),(1,2));self.assertTrue({Keyword.TAUNT,Keyword.DIVINE_SHIELD}<=set(e.keywords))
        self.assertEqual(len(g.state.card_summon_history),3)
        self.assertTrue(all(r.request.cause.source.entity_id==source for r in g.state.card_summon_history));self.portable(g)

    def test_b1_troupe_three_native_quantity_roots_and_actual_partial_capacity(self):
        for board,expected in(((TROUPE,DOUBLE),6),((TROUPE,)+(BEAST,)*5,2)):
            g=self.game((KILL,),board=board);self.play(g,KILL,self.first(g,TROUPE,'board').id)
            self.assertEqual(self.count(g,ANNOY),expected);self.assertEqual(len(g.state.players[1].board),7)
            self.assertEqual(len(g.state.card_summon_history),3);self.portable(g)

    def test_b2_troupe_wait_preserves_first_accepted_quantity_and_later_roots_recompute(self):
        g=self.game((KILL,),board=(TROUPE,DOUBLE),mode='troupe');self.play(g,KILL,self.first(g,TROUPE,'board').id)
        self.assertEqual(self.count(g,ANNOY),1);self.rollback(g);self.choose(g,'change')
        self.assertEqual(self.count(g,ANNOY),4);self.assertEqual(self.count(g,DOUBLE),0)
        self.assertEqual(len(g.state.card_summon_history),3);self.portable(g)

    def test_c0_paid_leviathan_dredges_original_card_then_its_claw_draws_that_exact_card(self):
        g=self.game((LEVIATHAN,),enemy=(BEAST,));source=self.play(g,LEVIATHAN);claw=self.first(g,CLAW,'board').id
        self.assertEqual(g.state.players[1].board,[source,claw]);self.assertEqual(g.state.players[1].mana,43)
        target=self.first(g,BEAST,'board',2).id;chosen=self.first(g,ALL,'deck').id
        g.apply(Attack(1,source,target));self.portable(g);self.dredge(g,ALL)
        self.assertEqual(g.state.players[1].deck[0],chosen);g.apply(Attack(1,claw,target))
        self.assertIn(chosen,g.state.players[1].hand);self.assertEqual(len(g.state.character_attack_history),2)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_c1_standalone_claw_after_actual_attack_draws_without_creating_colossal_body(self):
        g=self.game((CLAW,),enemy=(BEAST,));source=self.play(g,CLAW);top=g.state.players[1].deck[0]
        g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id));self.assertIn(top,g.state.players[1].hand)
        self.assertFalse(g.state.colossal_history);self.assertEqual(self.count(g,LEVIATHAN),0);self.portable(g)

    def test_c2_attributed_leviathan_native_quantity_produces_each_bodies_own_appendage(self):
        g=self.game((SUMMON,),board=(DOUBLE,));source=self.play(g,SUMMON)
        self.assertEqual((self.count(g,LEVIATHAN),self.count(g,CLAW)),(2,2))
        self.assertEqual(len(g.state.colossal_history),2);self.assertEqual(len(g.state.card_summon_history),1)
        self.assertEqual(g.state.card_summon_history[0].request.cause.source.entity_id,source);self.portable(g)

    def test_c3_colossal_body_fills_last_slot_and_does_not_invent_appendage_space(self):
        g=self.game((LEVIATHAN,),board=(BEAST,)*6);self.play(g,LEVIATHAN)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,CLAW),0)
        self.assertEqual(len(g.state.colossal_history),1);self.portable(g)

    def test_c4_dredge_wait_failure_and_physical_acquisition_preserve_other_deck_order(self):
        g=self.game((LEVIATHAN,),enemy=(BEAST,),mode='dredge');source=self.play(g,LEVIATHAN)
        chosen=self.first(g,ALL,'deck').id;others=[i for i in g.state.players[1].deck if i!=chosen]
        g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id));self.dredge(g,ALL)
        self.rollback(g);self.choose(g,'change');self.assertIn(chosen,g.state.players[1].hand)
        self.assertEqual(g.state.players[1].deck,others);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_d0_moon_places_sunken_at_bottom_without_semantic_random_shuffle(self):
        g=self.game((MOON,));old=g.state.players[1].deck;rng=g.snapshot()['rng_state'];self.play(g,MOON)
        self.assertEqual(g.state.players[1].deck[:-1],old);self.assertEqual(self.first(g,SUNKEN,'deck').id,g.state.players[1].deck[-1])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_d1_drawn_sunken_copies_its_current_buffed_body_without_repeating_battlecry(self):
        g=self.game((DRAW,BUFF),deck=(MECH,ALL,SUNKEN));self.play(g,DRAW);self.play(g,BUFF);source=self.play(g,SUNKEN)
        self.assertEqual(self.count(g,SUNKEN),2)
        for i in g.state.players[1].board:
            self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(5,4));self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[i].keywords)
        self.assertEqual(len(g.state.battlecry_history),1)
        self.assertEqual(g.state.card_summon_history[0].request.cause.source.entity_id,source);self.portable(g)

    def test_d2_original_sunken_copy_request_does_not_rebind_same_id_board_reentry(self):
        g=self.game((SUNKEN,),mode='sunken');source=self.play(g,SUNKEN);self.rollback(g);self.choose(g,'change')
        self.assertEqual(g.state.players[1].board,[source]);self.assertEqual(self.count(g,SUNKEN),1);self.portable(g)

    def test_e0_hellbat_other_friendly_attack_and_rush_aura_retires_on_silence(self):
        g=self.game((HELLBAT,MECH,SILENCE),board=(BEAST,),enemy=(BEAST,));source=self.play(g,HELLBAT)
        beast=self.first(g,BEAST,'board');self.assertEqual(beast.attack,4);self.assertIn(Keyword.RUSH,beast.keywords)
        self.assertEqual(g.state.entities[source].attack,4);self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords)
        self.assertEqual(self.first(g,BEAST,'board',2).attack,2);self.assertEqual(self.first(g,MECH).attack,1)
        mech=self.play(g,MECH);g.apply(Attack(1,mech,self.first(g,BEAST,'board',2).id));self.play(g,SILENCE,source)
        self.assertEqual(self.first(g,BEAST,'board').attack,2);self.assertNotIn(Keyword.RUSH,self.first(g,BEAST,'board').keywords);self.portable(g)

    def test_e1_hellbat_departure_removes_both_contributions_from_other_friendly_minion(self):
        g=self.game((HELLBAT,BOUNCE),board=(ALL,));source=self.play(g,HELLBAT);self.play(g,BOUNCE,source)
        e=self.first(g,ALL,'board');self.assertEqual(e.attack,1);self.assertNotIn(Keyword.RUSH,e.keywords);self.portable(g)

    def test_f0_noble_magnetic_host_attack_buffs_original_hand_minion_once(self):
        g=self.game((NOBLE,ALL,HIGH),board=(MECH,),enemy=(BEAST,));host=self.first(g,MECH,'board').id
        self.play(g,NOBLE,position=0);self.assertEqual((g.state.entities[host].attack,g.state.entities[host].health),(3,6))
        g.apply(Attack(1,host,self.first(g,BEAST,'board',2).id));e=self.first(g,ALL)
        self.assertEqual((e.attack,e.health),(2,5));self.assertEqual(len(g.state.character_attack_history),1)
        events=[e for e in g.events if e.kind=='stored_card_buffed'];self.assertEqual(len(events),1);self.assertEqual(events[0].source_id,host);self.portable(g)

    def test_f1_other_attacker_and_empty_minion_hand_do_not_consume_reward_rng(self):
        g=self.game((ALL,),board=(NOBLE,BEAST),enemy=(BEAST,));rng=g.snapshot()['rng_state']
        g.apply(Attack(1,self.first(g,BEAST,'board').id,self.first(g,BEAST,'board',2).id))
        self.assertEqual(self.first(g,ALL).attack,1);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
        g=self.game((HIGH,),board=(NOBLE,),enemy=(BEAST,));rng=g.snapshot()['rng_state']
        g.apply(Attack(1,self.first(g,NOBLE,'board').id,self.first(g,BEAST,'board',2).id))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(any(e.kind=='stored_card_buffed'for e in g.events));self.portable(g)

    def test_f2_accepted_original_attack_reward_survives_retirement_but_new_residency_cannot_rebind(self):
        g=self.game((ALL,),board=(NOBLE,),enemy=(BEAST,),mode='attack');source=self.first(g,NOBLE,'board').id
        g.apply(Attack(1,source,self.first(g,BEAST,'board',2).id))
        self.assertEqual(g.state.character_attack_history[0].terminal.status,'completed')
        self.assertEqual(self.first(g,ALL).attack,1);self.rollback(g);self.choose(g,'change')
        self.assertIn(source,g.state.players[1].board);self.assertEqual(self.first(g,ALL).attack,2)
        from hs_sim.engine.registry import RuleContext
        event=next(e for e in g.events if e.kind=='attack_finished')
        row=g.state.character_attack_history[0];current=g.state.entities[source]
        self.assertNotEqual((row.source_zone_epoch,row.source_entered_order),(current.zone_epoch,current.entered_order))
        self.assertEqual(g.registry.behavior(PREFIX+'noble')(RuleContext(g.state,source,1,event=event)),())
        self.portable(g)

    def test_g0_forge_pays_two_without_play_and_forged_battlecry_buffs_only_hand_minions(self):
        g=self.game((MUSCLE,GRYPHON,ALL,HIGH));source=self.first(g,MUSCLE).id
        g.apply(UseHandAction(1,source,'forge'));self.assertEqual(g.state.entities[source].card_id,FORGED)
        self.assertEqual(g.state.players[1].mana,48);self.assertFalse(g.state.play_history)
        self.assertEqual(self.first(g,GRYPHON).card_id,GRYPHON);self.play(g,FORGED)
        self.assertEqual(g.state.players[1].mana,45);self.assertEqual((self.first(g,ALL).attack,self.first(g,ALL).health),(3,6))
        self.assertEqual((self.first(g,GRYPHON).attack,self.first(g,GRYPHON).health),(7,7));self.assertEqual(self.first(g,HIGH).attack,0);self.portable(g)

    def test_g1_forge_notification_wait_restores_failed_choice_and_does_not_pay_twice(self):
        g=self.game((MUSCLE,ALL),mode='forge');source=self.first(g,MUSCLE).id;g.apply(UseHandAction(1,source,'forge'))
        self.assertEqual(g.state.entities[source].card_id,FORGED);self.rollback(g);self.choose(g)
        self.assertEqual(g.state.players[1].mana,48);self.play(g,FORGED);self.assertEqual(self.first(g,ALL).attack,3);self.portable(g)

    def test_g2_plain_and_forged_pending_hand_buffs_do_not_rebind_new_hand_acquisition(self):
        for cid,n in((MUSCLE,1),(FORGED,2)):
            g=self.game((cid,MECH,ALL),mode='buff');source=self.play(g,cid)
            self.assertEqual(self.first(g,MECH).attack,1+n);self.rollback(g);self.choose(g,'change')
            self.assertEqual(self.first(g,ALL).attack,1);self.assertEqual(g.state.entities[source].attack,2);self.portable(g)

    def test_z0_complete_sources_and_actual_new_ids_preserve_all_old_assembled_content(self):
        from tools.card_batch import check_face
        from hs_sim.targets import canonical_digest
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(0,11,40))
        rows={x['record']['id']:x['record']for k in('dependencies','existing_dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],{},numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        self.assertEqual(canonical_digest(asdict(after.card(ANNOY))),d['existing_dependency_definition_pins'][ANNOY]['sha256'])
        for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
        for cid in d['unsupported_source_cards']:self.assertEqual(cid in before.cards,cid in after.cards)


if __name__=='__main__':unittest.main()
