"""Actual permanent carriers, guarded Adapt, Jade bases and physical power draws."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from random import Random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p71_cards as cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p71_cards import (PORTAL_SPELL, PORTAL, GALVADON, JADES,
    AVATAR, STAR, SHELL, IMP, ROOTS, PREFIX, SOURCE_ROOTS, load_batch, register_simple_followup_p71_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, PlayCard, PlayerSetup, Rarity,
    Scenario, SelectChoice, TargetSpec, UseHeroPower, Zone)
from hs_sim.engine.adapt import CHOICE_IDS, PLANT_ID
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage, Destroy,
    InvokeBehavior, ReplaceHeroPower, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem
from hs_sim.engine.model import BoardPresenceReference, HeroPowerReference, LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyStoredCard
from hs_sim.targets import canonical_digest

TEST='p71.test.'
HERO,VICTIM,DEMON,ALL,POWER,DOUBLE,WIND,WATCH=(TEST+x for x in('hero','victim','demon','all','power','double','wind','watch'))
KILL,CLEAR,ONE,SIX,TWENTY,COPY,SILENCE,BOUNCE,BUFF,INJECT,SHREDS,INSTALL=(TEST+x for x in
    ('kill','clear','one','six','twenty','copy','silence','bounce','buff','inject','shreds','install'))
SHRED='TIME_025t'
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()


def meta(tribes=(),collectible=True,card_class=CardClass.NEUTRAL):
    return CardMetadata(collectible,(card_class,),Rarity.COMMON if collectible else None,tribes=tribes)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS)
    if not any(present):register_simple_followup_p71_cards(r)
    elif not all(present):raise AssertionError('P71 requires its complete assigned assembly')
    register_candidate_pool_metadata(r);r.validate();return r


def registry(mode=None):
    r=batch_registry()
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=SHELL,
        metadata=meta(collectible=False,card_class=CardClass.ROGUE)))
    for cid,atk,hp,tribes in((VICTIM,2,12,()),(DEMON,3,3,('demon',)),(ALL,3,4,('all',)),(POWER,1,20,()),(WIND,1,20,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=atk,health=hp,metadata=meta(tribes),
            keywords=(Keyword.WINDFURY,)if cid==WIND else(),spell_damage=6 if cid==POWER else 0))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        summon_quantities=(SummonQuantitySpec(2),),metadata=meta()))
    def inject(c,shreds=False):
        ids=(SHRED,SHRED)if shreds else(INJECT,VICTIM)
        work=tuple(AddToDeck(c.player_id,cid,source_id=c.source_id)for cid in ids)
        if mode=='shell':work+=(SummonByCard(2,(SummonEntryMaterial(WATCH),),SummonCause.capture(c)),)
        return work
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        CLEAR:lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].kind==CardType.MINION),
        ONE:lambda c:(SummonJadeGolem(c.player_id,c.source_id),),SIX:lambda c:(SummonJadeGolem(c.player_id,c.source_id,count=6),),
        TWENTY:lambda c:(SummonJadeGolem(c.player_id,c.source_id,count=20),),
        COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
        SILENCE:lambda c:(Silence(c.target_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        BUFF:lambda c:(Buff(c.target_id,3,4,c.source_id),),INJECT:inject,SHREDS:lambda c:inject(c,True),
        INSTALL:lambda c:(ReplaceHeroPower(c.player_id,STAR,HeroPowerReference.capture(
            c.state.entities[c.state.players[c.player_id].hero_power_id])),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec()if cid in(KILL,COPY,SILENCE,BOUNCE,BUFF)else None,metadata=meta()))
    def fail(c):raise ResolutionError('P71 deliberate continuation failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(TEST+'fail',fail);r.register_behavior(TEST+'reenter',reenter)
    if mode:
        events={'portal':('minion_summoned',),'adapt':('stats_changed','ability_granted'),
            'galv_start':('battlecry_started',),'avatar':('ability_granted',),'star':('minion_summoned',),
            'shell':('card_drawn',)}[mode]
        def eligible(c):
            if mode=='galv_start':return c.state.entities[c.event.source_id].card_id==GALVADON
            if mode=='shell':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==SHELL
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.controller!=1:return False
            if mode=='portal':return e.card_id==IMP
            if mode=='adapt':return e.card_id==GALVADON
            if mode=='avatar':return dict(c.event.data).get('ability_kind')=='trigger'
            return e.card_id==DEMON
        def wait(c):
            options=[ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))]
            if mode=='portal':
                p=next(c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id==PORTAL)
                options.append(ChoiceOption('remove','Retire original permanent portal',(RemoveFromGame((MinionReference.capture(p),),c.source_id),)))
            if mode in('adapt','avatar'):
                target=c.event.target_id
                options.append(ChoiceOption('cycle','Original recipient leaves and reenters',(
                    ReturnToHand(target),InvokeBehavior(TEST+'reenter',c.source_id,1,target))))
            if mode=='galv_start':options.append(ChoiceOption('kill','Remove original source',(Destroy(c.event.source_id,c.source_id),)))
            if mode=='star':
                p=c.state.entities[c.state.players[1].hero_power_id]
                options.append(ChoiceOption('swap','Replace original power',(ReplaceHeroPower(1,SHELL,HeroPowerReference.capture(p)),)))
            if mode=='shell':
                ids,_=starting_deck_identity(c.state)
                refs=[CardReference.capture(c.state.entities[i])for i in c.state.players[1].deck if i not in ids[0]]
                options.append(ChoiceOption('drop','Destroy remaining nonstarting candidates',tuple(DestroyStoredCard(ref,c.source_id)for ref in refs)))
                p=c.state.entities[c.state.players[1].hero_power_id]
                options.append(ChoiceOption('swap','Replace original power',(ReplaceHeroPower(1,STAR,HeroPowerReference.capture(p)),)))
            return(RequestChoice(1,tuple(options),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'wait',wait)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,metadata=meta(),
            limited_triggers=tuple(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible')for event in events)))
    r.validate();return r


@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
    if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Incomplete immutable fixture key')
    r=registry(mode);r.freeze();return r


class SimpleFollowupP71Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,power=SHELL,active=1,seed=7171):
        self.mode=mode
        if mode=='star':board=(WATCH,)+board
        elif mode:enemy=(WATCH,)+enemy
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(VICTIM,)*12,
            hero_power_card_id=power,mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,hand=enemy_hand,board=enemy,
            deck=(VICTIM,)*12,mana=40,max_mana=40,mana_cap=40)),seed=seed,active_player=active),
            fixture_registry(mode,'writer',SOURCE_PIN))
    def match(self,mode=None,fill=INJECT):
        self.mode=mode;r=fixture_registry(mode,'writer',SOURCE_PIN)
        policy=DeckPolicy(TEST+'policy','p71-explicit-original-decks','experimental',tuple(r.cards),max_copies=30)
        deck=DeckSpec(HERO,SHELL,CardClass.ROGUE,(fill,)*30)
        g=Game.from_decks(MatchSetup((deck,deck),policy,'GAME_005',seed=7171,first_player=1),r)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,pid=1):
        e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,
            position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
    def hero(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id]
    def portable(self,g):
        r=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,r)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in('rng_state','resolution_frame','behavior_id','source_allocation','jade_history','original_entities'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def adapt_all(self,g,spores=False):
        seen=False;rounds=0
        while g.state.pending_choice is not None:
            q=g.state.pending_choice
            if all(o.card_id in CHOICE_IDS for o in q.options):
                ids=[o.id for o in q.options];key='UNG_999t2'if spores and not seen and 'UNG_999t2'in ids else next(i for i in ids if i!='UNG_999t2')
                seen|=key=='UNG_999t2';rounds+=1;self.choose(g,key)
            else:break
        return rounds,seen

    def test_a0_portal_actual_reward_spell_permanent_carrier_and_two_owner_end_imps(self):
        g=self.game((PORTAL_SPELL,));self.play(g,PORTAL_SPELL);p=self.first(g,PORTAL,'board')
        self.assertTrue(p.dormancy.permanent);self.assertFalse(p.active);self.assertEqual(len(g.state.players[1].board),1)
        g.apply(EndTurn(1));self.assertEqual(self.count(g,IMP),2);g.apply(EndTurn(2));self.assertEqual(self.count(g,IMP),2)
        self.assertEqual(g.state.entities[p.id].zone,Zone.BOARD);self.portable(g)

    def test_a1_portal_wait_restore_rollback_and_retirement_does_not_cancel_accepted_second_imp(self):
        g=self.game((PORTAL_SPELL,),mode='portal');self.play(g,PORTAL_SPELL);source=self.first(g,PORTAL,'board').id
        g.apply(EndTurn(1));self.assertEqual(self.count(g,IMP),1);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'remove')
        self.assertEqual(g.state.entities[source].zone,Zone.SETASIDE);self.assertEqual(self.count(g,IMP),2);self.portable(g)

    def test_a2_portal_full_and_single_free_slot_use_actual_native_capacity(self):
        g=self.game((PORTAL_SPELL,),board=(VICTIM,)*7);self.play(g,PORTAL_SPELL)
        self.assertEqual(self.count(g,PORTAL),0);self.assertIsNone(g.state.card_summon_history[0].selected);self.portable(g)
        g=self.game((PORTAL_SPELL,),board=(VICTIM,)*5);self.play(g,PORTAL_SPELL);g.apply(EndTurn(1))
        self.assertEqual(self.count(g,IMP),1);self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_b0_galvadon_five_independent_native_offers_one_payment_and_waiting_restore(self):
        g=self.game((GALVADON,));self.play(g,GALVADON);self.portable(g)
        rounds,seen=self.adapt_all(g);self.assertEqual(rounds,5);self.assertFalse(seen)
        self.assertEqual(g.state.players[1].mana,35);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_b1_galvadon_original_reentry_stops_remaining_adaptations(self):
        g=self.game((GALVADON,),mode='adapt');source=self.play(g,GALVADON);q=g.state.pending_choice
        self.choose(g,q.options[0].id);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'cycle')
        self.assertIsNone(g.state.pending_choice);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,8));self.portable(g)

    def test_b2_actual_living_spores_uses_attributed_native_quantities_for_both_plants(self):
        g=self.game((GALVADON,KILL),board=(DOUBLE,),seed=5);source=self.play(g,GALVADON)
        rounds,seen=self.adapt_all(g,True);self.assertEqual(rounds,5);self.assertTrue(seen)
        self.play(g,KILL,source);self.assertEqual(self.count(g,PLANT_ID),4)
        self.assertTrue(all(r.request.cause.source.entity_id==source for r in g.state.card_summon_history));self.portable(g)

    def test_b3_galvadon_source_removed_before_body_has_no_adapt_or_new_recipient(self):
        g=self.game((GALVADON,),mode='galv_start');source=self.play(g,GALVADON);self.portable(g);self.choose(g,'kill')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_c0_jade_all_four_real_thresholds_and_full_attempts_share_native_growth(self):
        g=self.game((TWENTY,CLEAR,ONE));self.play(g,TWENTY)
        self.assertEqual(len(g.state.jade_history),20)
        self.assertEqual([g.state.jade_history[i].card_id for i in(0,3,6,19)],list(JADES))
        self.play(g,CLEAR);self.play(g,ONE);e=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.card_id,e.jade_size,e.attack,e.health,e.cost),(JADES[3],21,21,21,10));self.portable(g)

    def test_c1_jade_innate_size_survives_silence_current_copy_and_return_without_growth(self):
        g=self.game((SIX,BUFF,SILENCE,COPY,BOUNCE));self.play(g,SIX);source=g.state.players[1].board[-1]
        self.play(g,BUFF,source);self.play(g,SILENCE,source);self.play(g,COPY,source)
        copy=g.state.players[1].board[-1];self.assertEqual((g.state.entities[copy].jade_size,g.state.entities[copy].attack),(6,6))
        self.play(g,BOUNCE,source);self.assertEqual((g.state.entities[source].zone,g.state.entities[source].jade_size,g.state.entities[source].cost),(Zone.HAND,6,6))
        self.assertEqual(len(g.state.jade_history),6);self.portable(g)

    def test_c2_direct_jade_artwork_faces_are_physical_minions_without_invented_growth(self):
        g=self.game(JADES)
        for cid,size in zip(JADES,(1,4,7,20)):
            source=self.play(g,cid);self.assertEqual((g.state.entities[source].jade_size,g.state.entities[source].attack),(size,size))
        self.assertFalse(g.state.jade_history);self.portable(g)

    def test_d0_avatar_hero_attack_and_damage_are_native_then_both_grants_expire(self):
        g=self.game((AVATAR,),board=(POWER,),enemy=(VICTIM,));hero=self.hero(g).id;self.play(g,AVATAR,hero)
        self.assertEqual(self.hero(g).attack,2);g.apply(Attack(1,hero,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual(self.first(g,VICTIM,'board',2).health,10)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).attack,0);self.portable(g)

    def test_d1_avatar_unlimited_native_trigger_fires_for_each_completed_windfury_attack(self):
        g=self.game((AVATAR,),board=(WIND,),enemy=(VICTIM,));source=self.first(g,WIND,'board').id
        self.play(g,AVATAR,source);g.apply(Attack(1,source,self.first(g,VICTIM,'board',2).id));g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual((self.hero(g,2).health,self.first(g,VICTIM,'board',2).health),(23,5));self.portable(g)

    def test_d2_avatar_original_recipient_reentry_skips_delayed_attack_buff(self):
        g=self.game((AVATAR,),board=(VICTIM,),mode='avatar');source=self.first(g,VICTIM,'board').id;self.play(g,AVATAR,source)
        self.portable(g);self.choose(g,'cycle');self.assertEqual(g.state.entities[source].attack,2);self.portable(g)

    def test_e0_collapsing_star_printed_two_ignores_spell_power_and_own_demon_refreshes_original(self):
        g=self.game((DEMON,),board=(POWER,),power=STAR);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.hero(g,2).health,28);self.play(g,DEMON)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].uses_this_turn,0);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.hero(g,2).health,26);self.portable(g)

    def test_e1_collapsing_star_current_all_tribe_counts_but_opponent_demon_does_not(self):
        g=self.game((ALL,),enemy_hand=(DEMON,),power=STAR);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g,ALL)
        n=sum(e.kind=='hero_power_refreshed'for e in g.events);self.assertEqual(n,1)
        g.apply(EndTurn(1));self.play(g,DEMON,pid=2)
        self.assertEqual(sum(e.kind=='hero_power_refreshed'for e in g.events),n);self.portable(g)

    def test_e2_collapsing_star_old_queued_refresh_cannot_refresh_replacement_power(self):
        g=self.game((DEMON,INSTALL),mode='star');self.play(g,INSTALL)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g,DEMON)
        self.assertFalse(any(e.kind=='hero_power_refreshed'for e in g.events));self.portable(g);self.choose(g,'swap')
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,SHELL)
        self.assertFalse(any(e.kind=='hero_power_refreshed'for e in g.events));self.portable(g)

    def test_f0_shell_draws_original_nonstarting_entities_even_when_card_name_started_in_deck(self):
        g=self.match();self.play(g,INJECT);ids,_=starting_deck_identity(g.state)
        outside={i for i in g.state.players[1].deck if i not in ids[0]};self.assertEqual(len(outside),2)
        power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));rows=[r for r in g.state.draw_history if r.source_id==power]
        self.assertEqual({r.entity_id for r in rows},outside);self.assertEqual(len(rows),2);self.portable(g)

    def test_f1_shell_unknown_scenario_starting_identity_explicitly_errors_and_rolls_back(self):
        g=self.game();saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.snapshot(),saved)

    def test_f2_shell_wait_restore_rollback_requeries_remaining_physical_candidates(self):
        g=self.match('shell');self.play(g,INJECT);power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'drop')
        self.assertEqual(len([r for r in g.state.draw_history if r.source_id==power]),1);self.portable(g)

    def test_f3_shell_actual_draw_cast_shreds_keep_native_replacement_without_paid_hand_roots(self):
        g=self.match(fill=SHREDS);self.play(g,SHREDS);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.hero(g).health,24);self.assertEqual(len([r for r in g.state.cast_history if r.card_id==SHRED]),2)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(self.count(g,SHRED,'hand'),0);self.portable(g)

    def test_f4_shell_accepted_second_draw_continues_after_original_power_replacement(self):
        g=self.match('shell');self.play(g,INJECT);power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.portable(g);self.choose(g,'swap')
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,STAR)
        self.assertEqual(len([r for r in g.state.draw_history if r.source_id==power]),2);self.portable(g)

    def test_z0_complete_sources_dependency_only_counts_and_central_assembly_compatibility(self):
        from tools.card_batch import check_face
        d=load_batch();self.assertFalse(d['cards']);self.assertEqual(len(d['dependencies']),10);self.assertEqual(len(d['official_observations']),70)
        rows={x['record']['id']:x['record']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]}
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],
            d['display_normalizations'].get(o['card_id']),numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        before,after=build_registry(),batch_registry()
        for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
        for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
        self.assertEqual(before.fabled,after.fabled);self.assertEqual(before.player_effects,after.player_effects)
        for cid in SOURCE_ROOTS:self.assertEqual(cid in after.cards,cid in before.cards)
        for cid,pin in d['existing_dependency_definition_pins'].items():self.assertEqual(canonical_digest(asdict(after.card(cid))),pin['sha256'])
        self.assertEqual(after.jade_families[CLASSIC].forms,JADES)


if __name__=='__main__':unittest.main()
