"""Real immune-to-spellpower casts and both-side original summon attacks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_shred_treant_cards import ENTROPY,SHRED,TREES,TREANT,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,HealthFlow,HealthOp,
    HealthRule,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone,health_result)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,InvokeBehavior,
    RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.summon_attack_groups import SummonAttackProfile
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';SURGERY='JAIL_454';PREFIX='k99.'


def registry():
    r=build_registry()
    for name,attack,health in(('wall',1,30),('weak',0,2)):
        r.register_card(CardDefinition(PREFIX+name,name,CardType.MINION,attack=attack,health=health))
    r.register_card(CardDefinition(PREFIX+'power','Spell power',CardType.MINION,health=5,spell_damage=2))
    r.register_card(CardDefinition(PREFIX+'double','Ordinary source rule',CardType.MINION,health=5,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,source_relation='friendly',damage_kinds=(DamageKind.SPELL,)),)))
    r.register_behavior(PREFIX+'fail',lambda c:(AddToHand(c.player_id,'unknown.k99'),))
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(PREFIX+'reenter',reenter)
    def wait(c):
        if c.event.kind=='minion_summoned':
            entity=c.state.entities.get(c.event.target_id)
            if entity is None or entity.card_id!=TREANT or not c.state.cast_history:return ()
            cast=c.state.cast_history[-1]
            if cast.card_id!=TREES:return ()
            target=cast.target_id
        else:
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=ENTROPY:return ()
            target=c.event.target_id
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id),)),
            ChoiceOption('cycle','Return and reenter original target',(ReturnToHand(target),InvokeBehavior(PREFIX+'reenter',c.source_id,c.player_id,target))),
            ChoiceOption('transform','Transform continuous target',(Transform(target,PREFIX+'wall'),)),
        ),source_id=c.source_id),)
    for name,event in(('buff_wait','stats_changed'),('summon_wait','minion_summoned')):
        r.register_behavior(PREFIX+name,wait)
        r.register_card(CardDefinition(PREFIX+name,name,CardType.MINION,health=8,triggers=(TriggerSpec(event,PREFIX+name),)))
    def late(c):
        entity=c.state.entities.get(c.event.target_id)
        return(AddToHand(c.player_id,'unknown.k99'),)if entity is not None and entity.card_id==SHRED else ()
    r.register_behavior(PREFIX+'late',late)
    r.register_card(CardDefinition(PREFIX+'late','Shuffle observer',CardType.MINION,health=8,triggers=(TriggerSpec('card_added_to_deck',PREFIX+'late'),)))
    def nested(c):
        entity=c.state.entities[c.event.target_id]
        if entity.card_id!=TREANT:return ()
        # One unrelated same-name body, from a different printed source, after
        # the first original successful summon.
        if sum(c.state.entities[i].card_id==TREANT for i in c.state.players[c.player_id].board)==2:
            return(Summon(c.player_id,TREANT),)
        return ()
    r.register_behavior(PREFIX+'nested',nested)
    r.register_card(CardDefinition(PREFIX+'nested','Nested summon observer',CardType.MINION,health=8,triggers=(TriggerSpec('minion_summoned',PREFIX+'nested'),)))
    def local(c):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SHRED)
        return(GrantStoredSpellDamage(CardReference.capture(entity),5,c.source_id),)
    def defer(c):
        hit=Damage(c.state.players[c.player_id].hero_id,3,c.source_id,DamageKind.SPELL,spell_bonus_multiplier=0)
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(hit,)),),source_id=c.source_id),)
    scripts={'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'fill_draw':lambda c:(AddToHand(c.player_id,YETI,c.source_id),Draw(c.player_id,source_id=c.source_id)),
        'local':local,'defer':defer}
    for name,body in scripts.items():
        r.register_behavior(PREFIX+name,body);r.register_card(CardDefinition(PREFIX+name,name,CardType.SPELL,on_play=PREFIX+name))
    return r


class NativeShredTreantCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),deck=(YETI,)*8,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=99),self.r)
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i,target));return i
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for key in('spell_bonus_multiplier','RuleContext','resolution_frame','rng_state','SummonAttackProfile'):
                self.assertNotIn(key,public)
        return other
    def results(self,g):return[health_result(e)for e in g.events if e.kind=='health_resolved']
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def nodes(self,value,name):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+name):yield value['fields']
            for child in value.values():yield from self.nodes(child,name)
        elif isinstance(value,list):
            for child in value:yield from self.nodes(child,name)

    def test_complete_four_original_rows_eight_faces_and_actual_new_profile(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),8)
        for row in data['cards']+data['dependencies']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        raw=next(x['record']for x in data['dependencies']if x['record']['id']==SHRED)
        self.assertNotIn('COST',raw['tags']);self.assertIsNone(raw['cost']);self.assertEqual(raw['tags']['349'],1)
        self.assertEqual(self.r.summon_attack_profiles[TREES].combat_relation,'any_minions')
        self.assertEqual(self.r.summon_attack_profiles[SURGERY].combat_relation,'opponent')
        with self.assertRaises(ValueError):SummonAttackProfile(TREES,TREANT,4,'any')

    def test_shred_manual_real_spell_ignores_global_power_and_keeps_native_cast(self):
        for board in((),(PREFIX+'power',)):
            g=self.game((SHRED,),board=board);source=self.play(g,SHRED);result=self.results(g)[0]
            self.assertEqual((self.hero(g).health,result.base_amount,result.spell_bonus,result.damage_dealt),(27,3,0,3))
            self.assertEqual(result.damage_kind,DamageKind.SPELL.value);self.assertEqual(g.state.cast_history[-1].source_id,source)
            self.assertEqual(g.state.players[1].mana,40);self.portable(g)

    def test_shred_ignores_existing_source_local_spell_bonus_as_well(self):
        g=self.game((PREFIX+'local',SHRED),board=(PREFIX+'power',));self.play(g,PREFIX+'local');self.play(g,SHRED)
        result=self.results(g)[0];self.assertEqual((result.spell_bonus,result.damage_dealt,self.hero(g).health),(0,3,27));self.portable(g)

    def test_zero_coefficient_does_not_suppress_other_source_damage_modifiers(self):
        g=self.game((SHRED,),board=(PREFIX+'power',PREFIX+'double'));self.play(g,SHRED);result=self.results(g)[0]
        self.assertEqual((result.base_amount,result.spell_bonus,result.modified_amount,result.damage_dealt),(3,0,6,6))
        self.assertEqual(self.hero(g).health,24);self.portable(g)

    def test_two_actual_draw_cast_shreds_replace_until_real_card_without_hand_plays(self):
        g=self.game((PREFIX+'draw',),board=(PREFIX+'power',),deck=(SHRED,SHRED,YETI));self.play(g,PREFIX+'draw')
        self.assertEqual(self.hero(g).health,24);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len([c for c in g.state.cast_history if c.card_id==SHRED]),2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[YETI]);self.portable(g)

    def test_shred_replacement_empty_deck_keeps_ordinary_fatigue(self):
        g=self.game((PREFIX+'draw',),board=(PREFIX+'power',),deck=(SHRED,));self.play(g,PREFIX+'draw')
        self.assertEqual(self.hero(g).health,26);self.assertEqual([r.damage_kind for r in self.results(g)],[DamageKind.SPELL.value,DamageKind.FATIGUE.value]);self.portable(g)

    def test_full_hand_burn_does_not_cast_shred_or_replace_it(self):
        g=self.game((PREFIX+'fill_draw',)+(YETI,)*9,board=(PREFIX+'power',),deck=(SHRED,YETI));self.play(g,PREFIX+'fill_draw')
        self.assertEqual(self.hero(g).health,30);self.assertFalse(any(c.card_id==SHRED for c in g.state.cast_history))
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].deck),1);self.portable(g)

    def test_countered_shred_still_uses_native_counter_path_without_damage(self):
        g=self.game((SHRED,),board=(PREFIX+'power',),enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');g.apply(EndTurn(2));self.play(g,SHRED)
        self.assertEqual(self.hero(g).health,30);self.assertTrue(g.state.play_history[-1].countered);self.assertFalse(self.results(g));self.portable(g)

    def test_continuity_buffs_original_friends_then_one_two_card_shuffle(self):
        g=self.game((ENTROPY,),board=(YETI,),enemy=(YETI,),deck=());friend=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.play(g,ENTROPY);self.assertEqual((g.state.entities[friend].attack,g.state.entities[friend].health),(5,6))
        self.assertEqual((g.state.entities[enemy].attack,g.state.entities[enemy].health),(4,5))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[SHRED,SHRED]);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(g.state.players[1].mana,39);self.portable(g)

    def test_continuity_without_friends_still_shuffles_both_fixed_shreds(self):
        g=self.game((ENTROPY,),deck=());self.play(g,ENTROPY)
        self.assertEqual(len(g.state.players[1].deck),2);self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_buff_wait_restore_bad_choice_rollback_and_remaining_shuffle(self):
        g=self.game((ENTROPY,),board=(YETI,PREFIX+'buff_wait'),deck=());self.play(g,ENTROPY)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.deck_shuffle_history);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.finish(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].deck),2)

    def test_late_shuffle_failure_rolls_back_stats_payment_allocation_rng_and_history(self):
        g=self.game((ENTROPY,),board=(YETI,PREFIX+'late'),deck=());before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ENTROPY)
        self.assertEqual(g.snapshot(),before)

    def test_friendly_and_enemy_original_target_each_receive_four_real_attacks(self):
        for side in(1,2):
            g=self.game((TREES,),board=(PREFIX+'wall',)if side==1 else(),enemy=(PREFIX+'wall',)if side==2 else())
            target=g.state.players[side].board[0];self.play(g,TREES,target)
            self.assertEqual((len(g.state.character_attack_history),g.state.entities[target].health),(4,22))
            self.assertTrue(all(a.declaration.forced and a.declaration.combat_relation=='any_minions'for a in g.state.character_attack_history));self.portable(g)

    def test_treant_combat_ignores_spell_power_and_early_friendly_death_skips_tail(self):
        g=self.game((TREES,),board=(PREFIX+'weak',PREFIX+'power'));target=g.state.players[1].board[0]
        self.play(g,TREES,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.character_attack_history),1);self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id==TREANT]),4)
        self.assertTrue(all(r.damage_kind==DamageKind.COMBAT.value and r.spell_bonus==0 for r in self.results(g)));self.portable(g)

    def test_partial_and_full_board_do_not_refill_after_group_combat(self):
        for count,wanted in((6,1),(7,0)):
            g=self.game((TREES,),board=(YETI,)*count,enemy=(PREFIX+'wall',));self.play(g,TREES,g.state.players[2].board[0])
            self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id==TREANT]),wanted)
            self.assertEqual(len(g.state.character_attack_history),wanted)

    def test_old_same_name_and_nested_treants_are_not_borrowed_into_original_group(self):
        g=self.game((TREES,),board=(TREANT,PREFIX+'nested'),enemy=(PREFIX+'wall',));old=g.state.players[1].board[0]
        self.play(g,TREES,g.state.players[2].board[0]);self.assertEqual(len(g.state.character_attack_history),4)
        self.assertEqual(g.state.entities[old].attacks_this_turn,0);self.portable(g)

    def test_waiting_new_profile_restores_then_target_reentry_cannot_rebind_attacks(self):
        g=self.game((TREES,),board=(PREFIX+'summon_wait',PREFIX+'wall'));target=g.state.players[1].board[-1]
        self.play(g,TREES,target);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        for current in(g,other):self.choose(current,'cycle');self.finish(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(g.state.character_attack_history)
        self.assertEqual(g.state.entities[target].health,30)

    def test_waiting_new_profile_keeps_continuous_transformed_target(self):
        g=self.game((TREES,),board=(PREFIX+'summon_wait',YETI));target=g.state.players[1].board[-1]
        self.play(g,TREES,target);self.choose(g,'transform');self.finish(g)
        self.assertEqual(g.state.entities[target].health,22);self.assertEqual(len(g.state.character_attack_history),4);self.portable(g)

    def test_new_forced_relation_does_not_enable_normal_friendly_attack_or_hero_spell_target(self):
        g=self.game((TREES,),board=(PREFIX+'wall',YETI));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,g.state.players[1].board[0],g.state.players[1].board[1]))
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(IllegalAction):self.play(g,TREES,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),before)

    def test_zero_damage_request_roundtrips_in_actual_choice_and_replay(self):
        g=self.game((PREFIX+'defer',),board=(PREFIX+'power',));self.play(g,PREFIX+'defer');other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.hero(g).health,27)

    def test_rehashed_zero_request_rejects_bool_negative_or_wrong_damage_kind(self):
        g=self.game((PREFIX+'defer',));self.play(g,PREFIX+'defer')
        for field,value in(('spell_bonus_multiplier',True),('spell_bonus_multiplier',-1),('kind','effect')):
            saved=deepcopy(g.snapshot());nodes=list(self.nodes(saved,'Damage'));self.assertTrue(nodes)
            for node in nodes:
                if field=='kind'and isinstance(node[field],dict):node[field]['value']=value
                else:node[field]=value
            self.reject(saved)
