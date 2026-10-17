"""Rune conditions use actual payments, owner intervals and frozen original deaths."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p76_cards as cards
from hs_sim.cards.simple_followup_p76_cards import (HEMATURGE,MORTICIAN,STRIKE,PIT,DOG,BODYGUARD,
    KNIGHT,MAIDEN,HEALBOT,NIGHTBLADE,COMMANDO,SQUIRE,ROOTS,PREFIX,POOL_ID,load_batch,register_simple_followup_p76_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,
    Keyword,PlayerSetup,PlayCard,Rarity,Registry,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.dead_minion_shuffles import ShuffleDeadMinion
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GainResource,
    InvokeBehavior,RequestChoice,Silence,SpendResource)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,DamageKind,EndTurnSpec,LimitedTriggerSpec,Resource,Runes,SummonQuantitySpec,TribeChangeSpec,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import ChangeMinionTribes,has_any_tribe
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.zones import CardReference,DrawMatching

TEST='p76.test.'
HERO,HP,OTHER_HERO,OTHER_HP,FILLER,UND,ALL,BEAST,SMALL,BIG,SHIELD,REBORN,UNKNOWN_TRIBE,END_DYING,DOUBLE,POWER,WATCH=(TEST+i for i in
    ('hero','power','other-hero','other-power','filler','undead','all','beast','small','big','shield','reborn','unknown-tribe','end-dying','double','spellpower','watch'))
BLOOD,UNHOLY,FROST,MIX_BF,MIX_UF,SCHOOL,UNKNOWN=(TEST+i for i in('blood','unholy','frost-weapon','mixed-bf','mixed-uf','frost-school','unknown-runes'))
KILL,TO_UND,TO_BEAST,EXTRA,RESTORE,COPY,STEAL,HIT2,HURT,SILENCE=(TEST+i for i in('kill','to-undead','to-beast','extra','restore','copy','steal','hit2','hurt','silence'))
CONTEXT=GenerationContext(TEST,'experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
OFFERS={'blood':{BLOOD,MIX_BF},'unholy':{UNHOLY,MIX_UF},'frost':{FROST,MIX_BF,MIX_UF}}


def meta(tribes=(),collectible=True,cls=CardClass.NEUTRAL,runes=Runes()):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,runes=runes,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p76_cards(r)
    elif not all(present):raise AssertionError('P76 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=Registry('p76-small-native-fixtures');register_simple_followup_p76_cards(r)
    r.register_behavior(TEST+'nop',lambda c:())
    for hero,power,cls in((HERO,HP,CardClass.DEATH_KNIGHT),(OTHER_HERO,OTHER_HP,CardClass.MAGE)):
        r.register_card(CardDefinition(power,power,CardType.HERO_POWER,cost=2,on_use=TEST+'nop',metadata=meta(collectible=False,cls=cls)))
        r.register_card(CardDefinition(hero,hero,CardType.HERO,health=30,initial_hero_power=power,metadata=meta(collectible=False,cls=cls)))
    for cid,atk,hp,tribes,kw in((FILLER,0,20,(),()),(UND,1,3,('undead',),()),(ALL,1,3,('all',),()),(BEAST,1,5,('beast',),()),
            (SMALL,1,3,(),()),(BIG,1,5,(),()),(SHIELD,1,3,(),(Keyword.DIVINE_SHIELD,)),(REBORN,1,3,(),(Keyword.REBORN,)),(UNKNOWN_TRIBE,1,3,None,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=atk,health=hp,keywords=kw,metadata=meta(tribes)))
    r.register_behavior(TEST+'die',lambda c:(Destroy(c.source_id,c.source_id),))
    r.register_card(CardDefinition(END_DYING,END_DYING,CardType.MINION,attack=1,health=3,metadata=meta(('undead',)),triggers=(TriggerSpec('turn_ended',TEST+'die',EndTurnSpec()),)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=30,spell_damage=3,metadata=meta()))
    r.register_card(CardDefinition(BLOOD,BLOOD,CardType.MINION,cost=2,attack=2,health=3,metadata=meta(('undead',),cls=CardClass.DEATH_KNIGHT,runes=Runes(blood=1))))
    r.register_card(CardDefinition(UNHOLY,UNHOLY,CardType.SPELL,cost=2,on_play=TEST+'nop',spell_school=SpellSchool.FROST,metadata=meta(cls=CardClass.DEATH_KNIGHT,runes=Runes(unholy=1))))
    r.register_card(CardDefinition(FROST,FROST,CardType.WEAPON,cost=2,attack=1,durability=2,metadata=meta(cls=CardClass.DEATH_KNIGHT,runes=Runes(frost=1))))
    r.register_card(CardDefinition(MIX_BF,MIX_BF,CardType.SPELL,cost=2,on_play=TEST+'nop',spell_school=SpellSchool.FIRE,metadata=meta(cls=CardClass.DEATH_KNIGHT,runes=Runes(blood=1,frost=1))))
    r.register_card(CardDefinition(MIX_UF,MIX_UF,CardType.MINION,cost=2,attack=2,health=3,metadata=meta(cls=CardClass.DEATH_KNIGHT,runes=Runes(unholy=1,frost=1))))
    r.register_card(CardDefinition(SCHOOL,SCHOOL,CardType.SPELL,cost=2,on_play=TEST+'nop',spell_school=SpellSchool.FROST,metadata=meta(cls=CardClass.DEATH_KNIGHT)))
    members=[BLOOD,UNHOLY,FROST,MIX_BF,MIX_UF,SCHOOL]
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,2,meta(cls=CardClass.DEATH_KNIGHT,runes=None),attack=2));members.append(UNKNOWN)
    r.register_pool(PoolDefinition(POOL_ID,'p76-fixture',TEST,'experimental',tuple(PoolMember(i)for i in members)))
    def fail(c):raise ResolutionError('P76 deliberate continuation failure')
    def reenter(c):
        target=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(target),target.controller,cause=SummonCause.capture(c)),)
    def restore(c):
        row=next(d for d in reversed(c.state.death_history)if d.card_id==BEAST and d.controller==c.player_id)
        entity=c.state.entities[row.entity_id];request=ShuffleDeadMinion(SourceAllocationFact.capture(c.state,entity),row,c.player_id,c.source_id)
        return(ShuffleDeckCards(c.player_id,c.player_id,(request,),c.source_id),
            DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,)),'skip',selection='first',source_id=c.source_id,card_ids=(BEAST,)))
    def revive_same(c):
        entity=c.state.entities[c.target_id]
        row=next(d for d in reversed(c.state.death_history)if d.entity_id==entity.id and d.cause.target_zone_epoch+1==entity.zone_epoch)
        request=ShuffleDeadMinion(SourceAllocationFact.capture(c.state,entity),row,entity.controller,c.source_id)
        return(ShuffleDeckCards(entity.controller,c.player_id,(request,),c.source_id),
            DrawMatching(entity.controller,PoolQuery(kinds=(CardType.MINION,)),'skip',selection='first',source_id=c.source_id,card_ids=(entity.card_id,)),
            InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,entity.id))
    for name,body in(('fail',fail),('reenter',reenter),('revive',revive_same)):r.register_behavior(TEST+name,body)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),TO_UND:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),
        TO_BEAST:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('beast',)),c.source_id),),
        EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),RESTORE:restore,
        COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
        STEAL:lambda c:(ChangeControl(c.target_id,2),),HIT2:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),),
        HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,6,c.source_id,DamageKind.EFFECT),),SILENCE:lambda c:(Silence(c.target_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,TO_UND,TO_BEAST,COPY,STEAL,HIT2,SILENCE)else None,metadata=meta()))
    if mode in('bank','death','reaction'):
        event='battlecry_started'if mode=='bank'else'minion_died'if mode=='death'else'health_resolved'
        def eligible(c):
            if mode=='bank':return c.state.entities[c.event.source_id].card_id==HEMATURGE
            if mode=='death':
                ident=dict(c.event.data).get('death_id');row=next((d for d in c.state.death_history if d.id==ident),None)
                return row is not None and row.cause.health_result is not None and row.cause.health_result.source_card_id==STRIKE
            result=c.health_result
            return result is not None and result.source_card_id==STRIKE and result.damage_dealt>0
        def watcher(c):
            if mode=='bank':effects=(SpendResource(1,Resource.CORPSES,1),)
            elif mode=='death':
                ident=dict(c.event.data)['death_id'];row=next(d for d in c.state.death_history if d.id==ident)
                effects=(InvokeBehavior(TEST+'revive',c.source_id,c.player_id,row.entity_id),)
            else:effects=(Destroy(c.health_result.target_id,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original situation',effects),
                ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'pause',watcher)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta(),limited_triggers=(LimitedTriggerSpec(event,TEST+'pause',condition_id=TEST+'eligible'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP76Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode=None,corpses=0,enemy_hand=(),other_hero=False):
        self.mode=mode
        if mode in('bank','death'):enemy=(WATCH,)+enemy
        elif mode=='reaction':board=(WATCH,)+board
        hero,power=(OTHER_HERO,OTHER_HP)if other_hero else(HERO,HP)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(FILLER,)*12,mana=50,max_mana=50,mana_cap=50,corpses=corpses,hero_power_card_id=power),
            PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP)),seed=7676,generation_context=CONTEXT),fixture_registry(mode,'writer',SOURCE_PIN))
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def discover(self,g,rune,card=None):
        q=g.state.pending_choice;self.assertIsNotNone(q);self.assertEqual({o.card_id for o in q.options},OFFERS[rune])
        self.assertNotIn(SCHOOL,{o.card_id for o in q.options});self.choose(g,next(o.id for o in q.options if card is None or o.card_id==card))
    def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint())
        snap=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',visible)
    def rollback(self,g):
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)

    def test_a0_hematurge_zero_corpses_has_no_discovery_or_rng_and_one_actual_payment_unlocks_blood(self):
        g=self.game((HEMATURGE,));rng=g.snapshot()['rng_state'];self.play(g,HEMATURGE)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,48);self.portable(g)
        g=self.game((HEMATURGE,),corpses=1,other_hero=True);self.play(g,HEMATURGE);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.discover(g,'blood');self.assertEqual(len(g.state.corpse_spend_history),1);self.portable(g)

    def test_a1_real_hematurge_discovery_wait_recovers_without_repaying_or_repeating_on_copy(self):
        g=self.game((HEMATURGE,COPY),corpses=2);source=self.play(g,HEMATURGE);self.portable(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'not-an-offer')
        self.assertEqual(g.snapshot(),saved);self.discover(g,'blood',BLOOD);self.play(g,COPY,source)
        self.assertEqual(self.count(g,HEMATURGE),2);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(len(g.state.corpse_spend_history),1);self.portable(g)

    def test_a2_payment_rechecks_bank_after_real_battlecry_wait_and_failed_choice(self):
        g=self.game((HEMATURGE,),corpses=1,mode='bank');self.play(g,HEMATURGE);self.rollback(g);self.choose(g,'change')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertEqual(len(g.state.corpse_spend_history),1);self.assertTrue(any(e.kind=='resource_payment_skipped'for e in g.events));self.portable(g)

    def test_a3_unknown_rune_pool_fails_and_rolls_back_real_corpse_payment_but_unused_branch_skips_it(self):
        g=self.game((HEMATURGE,),corpses=1,mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,HEMATURGE)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
        g=self.game((HEMATURGE,),mode='unknown');self.play(g,HEMATURGE);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_b0_mortician_checks_actual_friendly_undead_death_after_last_owner_turn(self):
        g=self.game((MORTICIAN,),board=(UND,),enemy_hand=(KILL,));target=self.first(g,UND,'board').id
        g.apply(EndTurn(1));self.play(g,KILL,target,pid=2);g.apply(EndTurn(2));self.play(g,MORTICIAN)
        self.discover(g,'unholy',UNHOLY);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.portable(g)
        g=self.game((KILL,MORTICIAN),board=(UND,));self.play(g,KILL,self.first(g,UND,'board').id);self.next_own(g);self.play(g,MORTICIAN)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_b1_before_first_owner_history_all_and_current_tribe_are_real_frozen_death_facts(self):
        for cid,tool in((ALL,None),(BEAST,TO_UND)):
            g=self.game((KILL,MORTICIAN)+((tool,)if tool else()),board=(cid,));target=self.first(g,cid,'board').id
            if tool:self.play(g,tool,target)
            self.play(g,KILL,target);self.play(g,MORTICIAN);self.discover(g,'unholy');self.portable(g)
        g=self.game((TO_BEAST,KILL,MORTICIAN),board=(UND,));target=self.first(g,UND,'board').id
        self.play(g,TO_BEAST,target);self.play(g,KILL,target);self.play(g,MORTICIAN);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_b2_frozen_undead_death_survives_original_same_id_shuffle_draw_and_nonundead_reentry(self):
        g=self.game((TO_UND,KILL,RESTORE,MORTICIAN),board=(BEAST,));target=self.first(g,BEAST,'board').id
        self.play(g,TO_UND,target);self.play(g,KILL,target);self.play(g,RESTORE);self.assertEqual(self.first(g,BEAST).id,target)
        self.play(g,BEAST);self.assertFalse(has_any_tribe(g.registry,g.state.entities[target],('undead',)))
        self.play(g,MORTICIAN);self.discover(g,'unholy');self.assertEqual(g.state.death_history[0].entity_id,target);self.portable(g)

    def test_b3_extra_own_turn_uses_last_actual_closed_owner_and_end_death_stays_inside_old_turn(self):
        g=self.game((KILL,EXTRA,MORTICIAN),board=(UND,));self.play(g,KILL,self.first(g,UND,'board').id);self.play(g,EXTRA);g.apply(EndTurn(1))
        self.assertEqual([r.player_id for r in g.state.owner_turn_history],[1,1]);self.play(g,MORTICIAN);self.assertIsNone(g.state.pending_choice);self.portable(g)
        g=self.game((EXTRA,KILL,MORTICIAN),board=(UND,));self.play(g,EXTRA);g.apply(EndTurn(1));self.play(g,KILL,self.first(g,UND,'board').id)
        self.play(g,MORTICIAN);self.discover(g,'unholy');self.portable(g)
        g=self.game((MORTICIAN,),board=(END_DYING,));self.next_own(g);self.play(g,MORTICIAN);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_b4_death_controller_not_original_owner_determines_friendliness(self):
        g=self.game((STEAL,MORTICIAN),board=(UND,),enemy_hand=(KILL,));target=self.first(g,UND,'board').id
        self.play(g,STEAL,target);g.apply(EndTurn(1));self.play(g,KILL,target,pid=2);g.apply(EndTurn(2));self.play(g,MORTICIAN)
        self.assertIsNone(g.state.pending_choice);self.assertEqual((g.state.death_history[0].owner,g.state.death_history[0].controller),(1,2));self.portable(g)

    def test_b5_unknown_frozen_tribe_in_window_is_not_skipped_even_after_known_match_and_old_window_is_excluded(self):
        g=self.game((KILL,KILL,MORTICIAN),board=(UND,UNKNOWN_TRIBE));self.play(g,KILL,self.first(g,UND,'board').id)
        self.play(g,KILL,self.first(g,UNKNOWN_TRIBE,'board').id);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,MORTICIAN)
        self.assertEqual(g.snapshot(),saved);self.next_own(g);self.play(g,MORTICIAN);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_b6_second_player_uses_own_history_and_own_unholy_reward(self):
        g=self.game((KILL,),enemy=(UND,),enemy_hand=(MORTICIAN,));self.play(g,KILL,self.first(g,UND,'board',2).id);g.apply(EndTurn(1));self.play(g,MORTICIAN,pid=2)
        self.assertEqual(g.state.pending_choice.player_id,2);self.discover(g,'unholy',UNHOLY)
        self.assertEqual(self.first(g,UNHOLY,pid=2).controller,2);self.portable(g)

    def test_c0_strike_requires_minion_and_nonlethal_or_shield_damage_does_not_discover(self):
        for cid in(BIG,SHIELD):
            g=self.game((STRIKE,),enemy=(cid,));target=self.first(g,cid,'board',2).id
            with self.assertRaises(IllegalAction):self.play(g,STRIKE,g.state.players[2].hero_id)
            self.play(g,STRIKE,target);self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,48);self.portable(g)

    def test_c1_strike_actual_death_and_reborn_each_allow_rune_cards_of_all_types(self):
        for cid in(SMALL,REBORN):
            g=self.game((STRIKE,),enemy=(cid,));target=self.first(g,cid,'board',2).id;self.play(g,STRIKE,target)
            self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.discover(g,'frost',FROST)
            self.assertEqual(self.first(g,FROST).kind,CardType.WEAPON)
            if cid==REBORN:self.assertEqual(self.first(g,REBORN,'board',2).health,1)
            self.portable(g)

    def test_c2_strike_spell_damage_uses_actual_linked_result_not_printed_lethal_arithmetic(self):
        g=self.game((STRIKE,),board=(POWER,),enemy=(BIG,));self.play(g,STRIKE,self.first(g,BIG,'board',2).id)
        self.discover(g,'frost');self.assertEqual(g.state.death_history[0].cause.health_result.damage_dealt,6);self.portable(g)

    def test_c3_target_destroyed_by_later_damage_reaction_is_not_the_spells_original_kill(self):
        g=self.game((STRIKE,),enemy=(BIG,),mode='reaction');target=self.first(g,BIG,'board',2).id;self.play(g,STRIKE,target)
        self.rollback(g);self.choose(g,'change');self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.death_history[0].cause.kind,'destroy');self.portable(g)

    def test_c4_original_kill_wait_survives_same_id_reentry_but_cannot_pay_a_later_nonlethal_strike(self):
        g=self.game((HIT2,STRIKE,STRIKE),enemy=(BIG,),mode='death');target=self.first(g,BIG,'board',2).id
        self.play(g,HIT2,target);self.play(g,STRIKE,target);self.rollback(g);self.choose(g,'change')
        self.assertIn(target,g.state.players[2].board);self.assertEqual(g.state.entities[target].health,5);self.discover(g,'frost')
        self.play(g,STRIKE,target);self.assertEqual(g.state.entities[target].health,2);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_c5_unknown_rune_after_actual_lethal_damage_rolls_back_damage_death_payment_and_rng(self):
        g=self.game((STRIKE,),enemy=(SMALL,),mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,STRIKE,self.first(g,SMALL,'board',2).id)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_d0_actual_vanilla_bodies_and_taunt_have_exact_printed_costs_and_stats(self):
        g=self.game((PIT,DOG,BODYGUARD))
        for cid,stats in((PIT,(5,6)),(DOG,(7,4)),(BODYGUARD,(5,4))):
            source=self.play(g,cid);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),stats)
        self.assertIn(Keyword.TAUNT,self.first(g,BODYGUARD,'board').keywords);self.assertEqual(g.state.players[1].mana,35);self.portable(g)

    def test_d1_knight_summons_exact_squire_with_native_quantity_and_actual_capacity(self):
        g=self.game((KNIGHT,),board=(DOUBLE,));source=self.play(g,KNIGHT);self.assertEqual(self.count(g,SQUIRE),2)
        self.assertEqual(g.state.card_summon_history[0].request.cause.source.entity_id,source)
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(2,2)for i in g.state.players[1].board if g.state.entities[i].card_id==SQUIRE));self.portable(g)
        g=self.game((KNIGHT,),board=(FILLER,)*6);self.play(g,KNIGHT);self.assertEqual(self.count(g,SQUIRE),0);self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_d2_ordinary_copy_does_not_invent_another_knight_battlecry(self):
        g=self.game((KNIGHT,COPY));source=self.play(g,KNIGHT);self.play(g,COPY,source)
        self.assertEqual((self.count(g,KNIGHT),self.count(g,SQUIRE)),(2,1));self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_d3_armor_heal_and_enemy_or_selected_character_damage_use_native_nonspell_effects(self):
        g=self.game((HURT,MAIDEN,HEALBOT,NIGHTBLADE,COMMANDO),board=(POWER,));self.play(g,HURT);self.play(g,MAIDEN);self.play(g,HEALBOT)
        hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.health,hero.armor),(30,5))
        self.play(g,NIGHTBLADE);self.play(g,COMMANDO,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.assertEqual(g.state.players[1].mana,30)
        self.assertEqual(len(g.state.battlecry_history),4);self.portable(g)

    def test_z0_complete_sources_new_roots_and_known_current_family_remain_exact(self):
        from dataclasses import asdict
        from tools.card_batch import check_face
        from hs_sim.targets import canonical_digest
        d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(3,9,30))
        rows={x['record']['id']:x['record']for k in('cards','dependencies','evidence_only')for x in d[k]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id'],{}))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        for cid,pin in d['preserved_current_family_definition_pins'].items():self.assertEqual(canonical_digest(asdict(after.card(cid))),pin['sha256'])
        self.assertNotIn('EX1_028',ROOTS)
        for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
        for cid in d['unsupported_source_cards']:self.assertEqual(cid in before.cards,cid in after.cards)


if __name__=='__main__':unittest.main()
