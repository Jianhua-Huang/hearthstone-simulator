"""Thin actual Yogg adapter: original personal roots and existing random CAST."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.original_yogg_native import CARD,CAP,POOL,QUERY,load_batch,register_original_yogg_native
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition,CardType,CastWhenDrawnSpec,EndTurn,Game,PlayerSetup,
    Keyword,ResolutionError,Scenario,SpellRepeatSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,Overload,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardClass,CardMetadata,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.representative import build_registry
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import RecastSpell
from tools import card_batch as batch

S='k565.'
PLAIN,ARMOR,TARGET,NO_TARGET,CHOICE,OVERLOAD,GROW,DRAWN,BAD=(S+x for x in
 ('plain','armor','target','no_target','choice','overload','grow','drawn','bad'))
UNIT,AUTO,DRAWER,RECAST,REPEAT,CLEAR,WATCH,COUNTER=(S+x for x in
 ('unit','auto','drawer','recast','repeat','clear','watch','counter'))
CTX=GenerationContext('k565-original-yogg-native','experimental')
META=CardMetadata(True,(CardClass.PRIEST,),Rarity.COMMON)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    if mode=='frontier':
        from test_nefarian_native_dependencies import fixture as full_fixture
        r=full_fixture.__wrapped__('normal',role).registry
    else:
        r=build_registry();register_original_yogg_native(r)
    def fail(c):raise ResolutionError('k565 deliberate resume failure')
    def watch(c):
        event=c.event
        if event.kind!='spell_cast_started':return()
        cast=next(x for x in c.state.cast_history if x.id==dict(event.data)['cast_id'])
        if cast.origin!='effect' or cast.caster_id is None:return()
        source=c.state.entities[cast.caster_id]
        if source.card_id!=CARD or sum(x.caster_id==cast.caster_id and x.origin=='effect'for x in c.state.cast_history)!=1:
            return()
        effects={
            'death':lambda:(Destroy(source.id,c.source_id),),
            'bounce':lambda:(ReturnToHand(source.id),),
            'silence':lambda:(Silence(source.id),),
            'transform':lambda:(Transform(source.id,UNIT),),
            'control':lambda:(ChangeControl(source.id,3-c.player_id),),
            'terminal':lambda:(Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),),
        }
        if mode in effects:return effects[mode]()
        if mode=='wait':
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
        return()
    def counter(c):
        if c.state.entities[c.event.source_id].card_id==BAD:
            return(CounterSpell(dict(c.event.data)['window_id']),)
        return()
    r.register_behavior(S+'fail',fail);r.register_behavior(S+'watch',watch);r.register_behavior(S+'counter',counter)
    spells={
        PLAIN:lambda c:(),ARMOR:lambda c:(GainArmor(c.player_id,3),),
        TARGET:lambda c:(Damage(c.target_id,1,c.source_id),),NO_TARGET:lambda c:(),
        OVERLOAD:lambda c:(Overload(c.player_id,2),GainArmor(c.player_id,1)),GROW:lambda c:(Draw(c.player_id,1,c.source_id),),
        DRAWN:lambda c:(GainArmor(c.player_id,1),),BAD:lambda c:(),
        CHOICE:lambda c:(RequestChoice(c.player_id,(ChoiceOption('one','One',(GainArmor(c.player_id,1),)),
            ChoiceOption('three','Three',(GainArmor(c.player_id,3),))),c.source_id),),
    }
    for cid,body in spells.items():
        r.register_behavior(cid,body);fields={}
        if cid==TARGET:fields['targeting']=TargetSpec(kinds=(CardType.HERO,))
        if cid==NO_TARGET:fields['targeting']=TargetSpec(relation='enemy',zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if cid==DRAWN:fields.update(cast_when_drawn=CastWhenDrawnSpec(replacement=False),keywords=(Keyword.CASTS_WHEN_DRAWN,))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=7 if cid in (ARMOR,OVERLOAD)else 0,
            on_play=cid,metadata=META,**fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(UNIT,'Diagnostic body',CardType.MINION,attack=1,health=5))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,ARMOR,c.source_id),))
    r.register_behavior(DRAWER,lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_behavior(RECAST,lambda c:(RecastSpell(c.player_id,c.state.cast_history[0].id,c.source_id),))
    r.register_behavior(CLEAR,lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id==REPEAT))
    for cid in (AUTO,DRAWER,RECAST,CLEAR):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=4,battlecry=cid))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=5,spell_repeats=(SpellRepeatSpec(casts=2),)))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,durability=10,
        triggers=(TriggerSpec('spell_cast_started',S+'watch'),)))
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=5,
        triggers=(TriggerSpec('card_committed',S+'counter'),)))
    member={'targets':TARGET,'no_target':NO_TARGET,'choices':CHOICE,'overload':OVERLOAD}.get(mode,ARMOR)
    if mode!='unbound':
        r.register_pool(PoolDefinition(POOL,'yogg-single-spell-diagnostic-v1',CTX.target_id,CTX.mode,(PoolMember(member),),complete=True))
    if mode=='frontier':
        r.register_pool(PoolDefinition('constructed.past.cards','yogg-native-only-diagnostic-v1',CTX.target_id,CTX.mode,
            (PoolMember(CARD),),complete=True))
    r.validate();return r


class OriginalYoggNativeTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(fixture)

    def game(self,hand=(PLAIN,PLAIN,CARD),*,board=(),enemy=(),deck=(UNIT,)*5,mode='normal',player=1):
        self.mode=mode
        active=PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,
            weapon_card_id=WATCH if mode in ('wait','death','bounce','silence','transform','control','terminal')else None)
        other=PlayerSetup('HERO_01',board=enemy,deck=(UNIT,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((active,other)if player==1 else(other,active),
            active_player=player,seed=565,generation_context=CTX),fixture(mode))

    def casts(self,g,source):return[x for x in g.state.cast_history if x.caster_id==source and x.origin=='effect']
    def prepare(self,g,player=1):self.play(g,PLAIN,player=player);self.play(g,PLAIN,player=player)

    def test_complete_raw_primary_faces_and_native_ten_mana_seven_five(self):
        d=load_batch();row=next(x for x in batch.read(d['source'])if x['id']==CARD)
        self.assertEqual(d['cards'][0]['record'],row);self.assertEqual(batch.sha(d['source']),d['source_sha256'])
        for face in d['official_faces']:batch.check_face(row,face['face'],face['locale'])
        c=fixture().card(CARD);self.assertEqual((c.cost,c.attack,c.health),(10,7,5))
        self.assertEqual(CAP,30);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_actual_payment_counts_personal_roots_then_casts_freely_without_hand_plays(self):
        g=self.game();self.prepare(g);original_deck=tuple(g.state.players[1].deck);source=self.play(g,CARD)
        casts=self.casts(g,source)
        self.assertEqual(len(casts),2);self.assertTrue(all(c.card_id==ARMOR and c.completed and c.play_id is None for c in casts))
        self.assertEqual((len(g.state.play_history),g.state.players[1].mana),(3,50))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        self.assertEqual(tuple(g.state.players[1].deck),original_deck);self.portable(g)

    def test_zero_personal_spells_needs_no_pool_binding_and_consumes_no_rng(self):
        g=self.game((CARD,),mode='unbound');rng=g._rng.getstate();source=self.play(g,CARD)
        self.assertFalse(self.casts(g,source));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_nonzero_with_unbound_pool_fails_explicitly_and_rolls_back_paid_minion(self):
        g=self.game((PLAIN,CARD),mode='unbound');self.play(g,PLAIN);saved=g.snapshot()
        with self.assertRaises(Exception):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_countered_personal_spell_is_excluded_from_the_accepted_count(self):
        g=self.game((BAD,PLAIN,CARD),enemy=(COUNTER,));self.play(g,BAD);self.play(g,PLAIN)
        self.assertEqual(g.state.cast_history[0].failure,'countered');source=self.play(g,CARD)
        self.assertEqual(len(self.casts(g,source)),1);self.portable(g)

    def test_automatic_draw_and_history_casts_do_not_invent_personal_roots(self):
        g=self.game((AUTO,DRAWER,PLAIN,RECAST,CARD),deck=(DRAWN,UNIT))
        for cid in (AUTO,DRAWER,PLAIN,RECAST):self.play(g,cid)
        self.assertEqual({r.origin for r in g.state.cast_history},{'effect','draw','hand','history'})
        source=self.play(g,CARD);self.assertEqual(len(self.casts(g,source)),1)

    def test_repeated_manual_payload_has_one_personal_root(self):
        g=self.game((PLAIN,CLEAR,CARD),board=(REPEAT,));self.play(g,PLAIN)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','repeat'])
        self.play(g,CLEAR);source=self.play(g,CARD);self.assertEqual(len(self.casts(g,source)),1)

    def test_later_yogg_does_not_count_prior_yogg_automatic_spells(self):
        g=self.game((PLAIN,PLAIN,CARD,CARD));self.prepare(g);first=self.play(g,CARD);second=self.play(g,CARD)
        self.assertEqual([len(self.casts(g,s))for s in (first,second)],[2,2]);self.portable(g)

    def test_source_departure_silence_transform_and_control_keep_accepted_caster_and_count(self):
        for mode in ('death','bounce','silence','transform','control'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.prepare(g);source=self.play(g,CARD);casts=self.casts(g,source)
                self.assertEqual(len(casts),2);self.assertTrue(all(c.player_id==1 and c.completed for c in casts))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
                if mode=='control':self.assertEqual(g.state.entities[source].controller,2)
                elif mode=='death':self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                elif mode=='bounce':self.assertEqual(g.state.entities[source].zone,Zone.HAND)
                elif mode=='transform':self.assertEqual(g.state.entities[source].card_id,UNIT)

    def test_random_legal_hero_targets_and_random_spell_choices_use_original_automatic_pipeline(self):
        for mode in ('targets','choices'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.prepare(g);source=self.play(g,CARD);casts=self.casts(g,source)
                self.assertEqual(len(casts),2);self.assertTrue(all(c.completed and c.failure is None for c in casts))
                self.assertIsNone(g.state.pending_choice)
                if mode=='targets':
                    self.assertTrue(all(c.target_id in {p.hero_id for p in g.state.players.values()}for c in casts))
                else:self.assertIn(g.state.entities[g.state.players[1].hero_id].armor,(2,4,6))
                self.portable(g)

    def test_no_target_attempts_consume_slots_and_overload_uses_ordinary_resource_path(self):
        for mode in ('no_target','overload'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.prepare(g);source=self.play(g,CARD);casts=self.casts(g,source)
                self.assertEqual(len(casts),2);self.assertEqual(g.state.players[1].mana,50)
                if mode=='no_target':self.assertTrue(all(c.failure=='no_target'for c in casts))
                else:self.assertEqual(g.state.players[1].overload_owed,4)

    def test_automatic_start_wait_restores_pending_batch_and_failed_resume_is_atomic(self):
        g=self.game(mode='wait');self.prepare(g);source=self.play(g,CARD)
        self.assertEqual(len(self.casts(g,source)),1);self.assertIsNotNone(g.state.pending_choice)
        restored=self.portable(g);saved=restored.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate resume failure'):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        for game in (g,restored):self.choose(game)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.casts(g,source)),2);self.portable(g)

    def test_terminal_first_automatic_cast_does_not_start_the_remaining_slot(self):
        g=self.game(mode='terminal');self.prepare(g);source=self.play(g,CARD)
        self.assertEqual((g.state.status,len(self.casts(g,source))),('finished',1));self.portable(g)

    def test_native_repeated_battlecry_recaptures_personal_count_without_feedback(self):
        g=self.game(board=('LOE_077',));self.prepare(g);source=self.play(g,CARD)
        self.assertEqual(len(self.casts(g,source)),4);self.assertEqual(len(g.state.play_history),3);self.portable(g)

    def test_actual_thirty_one_personal_roots_are_capped_at_thirty_generated_casts(self):
        g=self.game((GROW,CARD),deck=(GROW,)*30)
        for _ in range(31):self.play(g,GROW)
        self.assertEqual(len(g.state.cast_history),31);source=self.play(g,CARD)
        self.assertEqual(len(self.casts(g,source)),30);self.assertEqual(len(g.state.play_history),32)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,90)

    def test_second_seat_uses_own_root_history_and_original_accepting_player(self):
        g=self.game(player=2);self.prepare(g,player=2);source=self.play(g,CARD,player=2)
        casts=self.casts(g,source);self.assertEqual(len(casts),2)
        self.assertTrue(all(c.player_id==2 for c in casts));self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,6)

    def test_public_waiting_view_does_not_expose_spell_batch_rng_or_full_history(self):
        g=self.game(mode='wait');self.prepare(g);self.play(g,CARD);saved=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('ContinuePoolCasts','resolution_frame','cast_history','rng_before','rng_state','used_identities'):
                self.assertNotIn('"'+key+'"',view)
        self.assertEqual(g.snapshot(),saved)

    def test_real_frontier_discovery_restore_set_one_then_native_random_spell_battlecry(self):
        r=fixture('frontier');members=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=CardClass.DRUID,source_card_id='GDB_857',player_id=1)
        self.assertEqual([(m.card_id,m.weight)for m in members],[(CARD,1)])
        g=self.game((PLAIN,PLAIN,'GDB_857'),mode='frontier');self.prepare(g);self.play(g,'GDB_857')
        restored=self.portable(g)
        for game in (g,restored):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            source=self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,1)
            self.assertEqual([row.card_id for row in game.state.cast_history if row.origin=='hand'],[PLAIN,PLAIN,'GDB_857'])
            self.assertEqual(len(self.casts(game,source)),3)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)


if __name__=='__main__':unittest.main()
