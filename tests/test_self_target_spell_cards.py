"""Shared original-minion preference and two actual casting/recasting consumers."""
from copy import deepcopy
from dataclasses import asdict
import json, unittest
from hs_sim.cards import build_registry
from hs_sim.cards.self_target_spell_cards import load_batch
from hs_sim.engine import (BoardPresenceReference, CardDefinition, CardType, CostSpec,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice,
    SnapshotError, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.automatic_targets import PreferredMinionTarget, selection_from_dict
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.spell_history import RecastFromHistory, SpellHistoryQuery
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import canonical_digest

FISH='TLC_438'; CAVE='TLC_430'; HOLY='CS2_236'; YETI='CORE_CS2_182'; ROCK='WW_001t'


def small_registry(route='generated', relation='any', displacement=None, waiting=False, untargeted=False):
    r=Registry('preferred-original-minion-tests-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    for cid in ('caster','other','enemy'):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=10))
    r.register_behavior('fail',lambda c:(AddToHand(c.player_id,'missing',c.source_id),))
    def body(c):
        if waiting and c.cast.origin!='hand':
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',(GainArmor(c.state.players[c.player_id].hero_id,1),)),
                ChoiceOption('bad','Fail',(InvokeBehavior('fail',c.source_id,c.player_id),))),source_id=c.source_id),)
        return(Buff(c.target_id,attack=1,source_id=c.source_id),)if c.target_id is not None else()
    r.register_behavior('body',body)
    r.register_card(CardDefinition('spell','Spell',CardType.SPELL,cost=1,on_play='body',spell_school=SpellSchool.HOLY,
        targeting=None if untargeted else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation=relation)))
    def resummon(c):
        return(SummonStoredCard(CardReference.capture(c.state.entities[c.source_id]),c.player_id),)
    r.register_behavior('resummon',resummon)
    def launch(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='caster')
        ref=BoardPresenceReference.capture(c.state,source.id)
        if displacement=='future':ref=BoardPresenceReference(source.id,c.state.next_order+999)
        pref=PreferredMinionTarget(ref)
        before=()
        if displacement=='kill':before=(Destroy(source.id,c.source_id),)
        elif displacement=='bounce':before=(ReturnToHand(source.id),InvokeBehavior('resummon',source.id,c.player_id))
        elif displacement=='transform':before=(Transform(source.id,'other'),)
        elif displacement=='give':before=(ChangeControl(source.id,3-c.player_id),)
        if route=='stored':
            request=CastRandomDeckSpell(c.player_id,2,source.id,pref)
        elif route=='history':
            request=RecastFromHistory(c.player_id,SpellHistoryQuery(),count=1,selection='random',
                source_id=source.id,choices='player',target_preference=pref)
        else:request=CastSpell(c.player_id,'spell',source.id,choices='player',target_preference=pref)
        return(*before,request)
    r.register_behavior('launch',launch)
    r.register_card(CardDefinition('launch','Launch',CardType.SPELL,on_play='launch'))
    return r


class PreferredMinionTargetTests(unittest.TestCase):
    def game(self,enemy=('enemy',),**config):
        self.config=config
        return Game.from_scenario(Scenario((PlayerSetup('hero',board=('caster','other'),hand=('spell','launch'),
            deck=('spell',),mana=10,max_mana=10),PlayerSetup('hero',board=enemy)),seed=1064),small_registry(**config))
    def find(self,g,cid,zone='board'):
        s=g.state;return next(i for i in getattr(s.players[1],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None):g.apply(PlayCard(1,self.find(g,cid,'hand'),target))
    def launch(self,**config):
        g=self.game(**config)
        if config.get('route')=='history':self.play(g,'spell',self.find(g,'other'))
        self.play(g,'launch');return g
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,small_registry(**self.config)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),small_registry(**self.config)).snapshot(),s)
    def test_generated_cast_prefers_original_minion(self):
        g=self.launch();cast=g.state.cast_history[-1]
        self.assertEqual(cast.target_id,self.find(g,'caster'));self.assertEqual(cast.target_selection.partition.preferred_id,cast.target_id)
        self.portable(g)
    def test_preferred_target_does_not_consume_target_rng(self):
        g=self.launch();selection=g.state.cast_history[-1].target_selection
        self.assertEqual(selection.rng_before,selection.rng_after)
        self.assertGreater(len(selection.partition.legal_ids),1)
    def test_physical_deck_cast_keeps_entity_and_creates_no_play_or_draw(self):
        g=self.game(route='stored');eid=g.state.players[1].deck[0];self.play(g,'launch');cast=g.state.cast_history[-1]
        self.assertEqual((cast.source_id,cast.from_zone),(eid,Zone.DECK));self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(g.state.draw_history);self.portable(g)
    def test_historical_recast_uses_same_preference(self):
        g=self.launch(route='history');cast=g.state.cast_history[-1]
        self.assertEqual((cast.origin,cast.recast_id,cast.target_id),('history',1,self.find(g,'caster')));self.portable(g)
    def test_illegal_friendly_original_falls_back_to_legal_enemy(self):
        g=self.launch(relation='enemy');selection=g.state.cast_history[-1].target_selection
        self.assertIsNone(selection.partition.preferred_id)
        self.assertEqual(selection.target_id,g.state.players[2].board[0]);self.assertNotEqual(selection.rng_before,selection.rng_after)
    def test_departed_original_falls_back_without_targeting_dead_source(self):
        g=self.launch(displacement='kill');cast=g.state.cast_history[-1]
        self.assertIsNone(cast.target_selection.partition.preferred_id)
        self.assertNotEqual(cast.target_id,cast.caster_id);self.portable(g)
    def test_reentry_is_not_preferred_but_can_remain_in_random_domain(self):
        g=self.launch(displacement='bounce');selection=g.state.cast_history[-1].target_selection
        self.assertIsNone(selection.partition.preferred_id)
        self.assertIn(g.state.cast_history[-1].caster_id,selection.partition.legal_ids);self.portable(g)
    def test_same_residence_transform_keeps_preference(self):
        g=self.launch(displacement='transform');cast=g.state.cast_history[-1]
        self.assertEqual(cast.target_id,cast.caster_id);self.assertEqual(cast.target_selection.partition.preferred_id,cast.caster_id)
    def test_same_residence_control_change_keeps_legal_preference(self):
        g=self.launch(displacement='give');cast=g.state.cast_history[-1]
        self.assertEqual(cast.target_id,cast.caster_id);self.assertEqual(g.state.entities[cast.target_id].controller,2);self.portable(g)
    def test_required_empty_target_domain_fails_without_target_rng(self):
        g=self.launch(enemy=(),relation='enemy');cast=g.state.cast_history[-1]
        self.assertEqual(cast.failure,'no_target');self.assertEqual(cast.target_selection.rng_before,cast.target_selection.rng_after)
    def test_untargeted_spell_ignores_preferred_minion(self):
        g=self.launch(untargeted=True);cast=g.state.cast_history[-1]
        self.assertIsNone(cast.target_id);self.assertIsNone(cast.target_selection.partition.preferred_id);self.portable(g)
    def test_preference_must_bind_actual_causing_source(self):
        pref=PreferredMinionTarget(BoardPresenceReference(10,20))
        with self.assertRaises(ValueError):CastSpell(1,'spell',11,target_preference=pref)
        with self.assertRaises(ValueError):CastRandomDeckSpell(1,2,11,pref)
    def test_future_reference_rejects_and_rolls_back(self):
        g=self.game(displacement='future');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'launch')
        self.assertEqual(g.snapshot(),before)
    def test_waiting_original_target_proof_restores_and_resumes(self):
        g=self.launch(waiting=True);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        before=g.snapshot();choice=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,choice.id,('bad',)))
        self.assertEqual(g.snapshot(),before);g.apply(SelectChoice(1,choice.id,('ok',)));self.portable(g)
    def test_saved_preferred_target_cannot_be_reassigned(self):
        g=self.launch(waiting=True);bad=g.snapshot()
        bad['state']['cast_history'][-1]['target_selection']['partition']['preferred_id']=g.state.players[2].board[0]
        bad['state_hash']=canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,small_registry(**self.config))
    def test_saved_original_reference_cannot_borrow_future_presence(self):
        g=self.launch(waiting=True);bad=g.snapshot()
        bad['state']['cast_history'][-1]['target_selection']['partition']['preference']['reference']['presence_id']=g.state.next_order+999
        bad['state_hash']=canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,small_registry(**self.config))
    def test_complete_selection_wire_roundtrip_and_unknown_field_rejection(self):
        g=self.launch();selection=g.state.cast_history[-1].target_selection
        wire=json.loads(json.dumps(asdict(selection)));self.assertEqual(selection_from_dict(wire),selection)
        wire['partition']['preference']['extra']=True
        with self.assertRaises(ValueError):selection_from_dict(wire)
    def test_selection_wire_missing_resolved_preference_is_rejected(self):
        g=self.launch();wire=json.loads(json.dumps(asdict(g.state.cast_history[-1].target_selection)))
        wire['partition'].pop('preferred_id')
        with self.assertRaises(ValueError):selection_from_dict(wire)


def native_registry():
    r=build_registry()
    def change_cost(c,delta):
        card=c.state.entities[c.state.players[c.player_id].deck[0]]
        return(ModifyStoredCost(CardReference.capture(card),CostSpec(delta=delta),c.source_id),)
    def wait(c):
        cast=c.state.cast_history[dict(c.event.data)['cast_id']-1]
        if cast.origin in ('hand','repeat'):return()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.state.players[c.player_id].hero_id,1),)),),source_id=c.source_id),)
    bodies=dict(reduce=lambda c:change_cost(c,-2),raise_cost=lambda c:change_cost(c,1),
        silence=lambda c:(Silence(c.target_id),),give=lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        summon=lambda c:(Summon(c.player_id,FISH),),blast=lambda c:(Damage(c.target_id,10,c.source_id,DamageKind.SPELL),))
    for name,body in bodies.items():
        r.register_behavior('k64.'+name,body)
        r.register_card(CardDefinition('k64.'+name,name,CardType.SPELL,on_play='k64.'+name,
            requires_target=name in ('silence','give','blast'),spell_school=SpellSchool.HOLY if name=='blast'else None))
    r.register_behavior('k64.wait',wait)
    r.register_card(CardDefinition('k64.wait','Reaction wait',CardType.MINION,health=5,
        triggers=(TriggerSpec('spell_cast_started','k64.wait'),)))
    return r


class SelfTargetSpellCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=native_registry()
    def game(self,hand=(),board=(),deck=(YETI,)*8,enemy=(),enemy_hand=(),seed=1064):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30)),seed=seed),self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.entity(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,native_registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),native_registry()).snapshot(),s)
    def test_complete_two_real_faces_and_distinct_native_entries(self):
        data=load_batch();self.assertEqual([x['record']['id']for x in data['cards']],[FISH,CAVE])
        for x in data['cards']:self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
        self.assertIsNotNone(self.r.card(FISH).battlecry);self.assertIsNone(self.r.card(CAVE).battlecry)
    def test_treasuregill_casts_original_deck_spell_on_itself_without_payment_or_draw(self):
        g=self.game((FISH,),deck=(HOLY,));spell_id=g.state.players[1].deck[0];eid=self.play(g,FISH);cast=g.state.cast_history[-1]
        self.assertEqual(g.state.entities[eid].health,4);self.assertEqual((cast.source_id,cast.target_id,cast.caster_id),(spell_id,eid,eid))
        self.assertEqual(g.state.players[1].mana,28);self.assertEqual(len(g.state.play_history),1);self.assertFalse(g.state.draw_history);self.portable(g)
    def test_treasuregill_empty_or_ineligible_deck_does_not_use_rng_or_fatigue(self):
        for deck in ((),(YETI,'CS2_029')):
            g=self.game((FISH,),deck=deck);before=g.snapshot()['rng_state'];self.play(g,FISH)
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.cast_history);self.assertFalse(g.state.draw_history)
    def test_treasuregill_uses_reduced_stored_deck_cost(self):
        g=self.game(('k64.reduce',FISH),deck=('CS2_029',));self.play(g,'k64.reduce');eid=self.play(g,FISH)
        self.assertEqual(g.state.cast_history[-1].card_id,'CS2_029');self.assertEqual(g.state.cast_history[-1].target_id,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.portable(g)
    def test_treasuregill_rejects_spell_whose_stored_cost_was_raised(self):
        g=self.game(('k64.raise_cost',FISH),deck=(HOLY,));self.play(g,'k64.raise_cost');self.play(g,FISH)
        self.assertEqual([x.card_id for x in g.state.cast_history],['k64.raise_cost'])
        self.assertEqual(len(g.state.players[1].deck),1)
    def test_hand_only_spell_discounts_do_not_qualify_deck_spells(self):
        g=self.game((FISH,),board=('EX1_608','EX1_608'),deck=('CS2_029',));self.play(g,FISH)
        self.assertFalse(g.state.cast_history)
    def test_real_battlecry_repeat_casts_two_different_physical_spells(self):
        g=self.game((FISH,),board=('TIME_064',),deck=(HOLY,HOLY));eid=self.play(g,FISH)
        self.assertEqual(g.state.entities[eid].health,8);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(len({x.source_id for x in g.state.cast_history}),2);self.assertEqual(g.state.players[1].mana,28);self.portable(g)
    def test_repeated_battlecry_still_casts_after_original_source_dies(self):
        g=self.game((FISH,),board=('TIME_064',),deck=(ROCK,'CORE_CS1_130'));eid=self.play(g,FISH)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.cast_history),2)
        self.assertIsNone(g.state.cast_history[-1].target_selection);self.portable(g)
    def test_effect_summon_does_not_execute_treasuregill_battlecry(self):
        g=self.game(('k64.summon',),deck=(HOLY,));self.play(g,'k64.summon')
        self.assertEqual([x.card_id for x in g.state.cast_history],['k64.summon'])
        self.assertEqual(len(g.state.players[1].deck),1)
    def test_cave_recasts_current_turn_holy_spell_on_original_self(self):
        g=self.game((HOLY,),board=(CAVE,YETI));self.play(g,HOLY,self.entity(g,YETI).id);g.apply(EndTurn(1))
        self.assertEqual(self.entity(g,CAVE).health,10);cast=g.state.cast_history[-1]
        self.assertEqual((cast.origin,cast.recast_id,cast.target_id),('history',1,self.entity(g,CAVE).id));self.portable(g)
    def test_cave_no_matching_holy_history_does_not_use_rng(self):
        g=self.game(board=(CAVE,));before=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.cast_history)
    def test_cave_does_not_recast_non_holy_spell(self):
        g=self.game((ROCK,),board=(CAVE,));self.play(g,ROCK,g.state.players[2].hero_id);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(self.entity(g,CAVE).health,5)
    def test_cave_does_not_use_previous_turn_holy_spell(self):
        g=self.game((HOLY,CAVE),board=(YETI,));self.play(g,HOLY,self.entity(g,YETI).id)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,CAVE);g.apply(EndTurn(1))
        self.assertEqual(self.entity(g,CAVE).health,5);self.assertEqual(len(g.state.cast_history),1)
    def test_cave_silence_prevents_end_recast(self):
        g=self.game((HOLY,'k64.silence'),board=(CAVE,YETI));self.play(g,HOLY,self.entity(g,YETI).id)
        self.play(g,'k64.silence',self.entity(g,CAVE).id);g.apply(EndTurn(1));self.assertEqual(len(g.state.cast_history),2)
    def test_cave_real_end_repetition_requeries_actual_history(self):
        g=self.game((HOLY,),board=('TIME_064',CAVE,YETI));self.play(g,HOLY,self.entity(g,YETI).id);g.apply(EndTurn(1))
        self.assertEqual(self.entity(g,CAVE).health,20);self.assertEqual(len(g.state.cast_history),3);self.portable(g)
    def test_cave_repeat_after_self_lethal_cast_falls_back(self):
        g=self.game(('k64.blast',),board=('TIME_064',CAVE),enemy=(YETI,));self.play(g,'k64.blast',self.entity(g,YETI,2).id)
        eid=self.entity(g,CAVE).id;g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.cast_history),3);self.portable(g)
    def test_cave_uses_current_controller_own_holy_history(self):
        g=self.game(('k64.give',),board=(CAVE,),enemy=(YETI,),enemy_hand=(HOLY,));eid=self.entity(g,CAVE).id
        self.play(g,'k64.give',eid);g.apply(EndTurn(1));self.play(g,HOLY,self.entity(g,YETI,2).id,p=2);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[eid].health,10);self.portable(g)
    def test_real_deck_cast_target_proof_survives_waiting_reaction(self):
        g=self.game((FISH,),board=('k64.wait',),deck=(HOLY,));eid=self.play(g,FISH)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)));self.assertEqual(g.state.entities[eid].health,4);self.portable(g)
    def test_real_holy_history_recast_survives_waiting_end(self):
        g=self.game((HOLY,),board=(CAVE,YETI,'k64.wait'));self.play(g,HOLY,self.entity(g,YETI).id);g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)));self.assertEqual(self.entity(g,CAVE).health,10);self.portable(g)
    def test_player_queries_hide_target_partition_and_preserve_rng(self):
        g=self.game((FISH,),deck=(HOLY,YETI));self.play(g,FISH);before=g.snapshot()
        for p in (1,2):
            self.assertNotIn('target_selection',json.dumps(g.observe(p)));g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
