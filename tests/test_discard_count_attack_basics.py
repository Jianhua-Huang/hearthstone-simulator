"""One native discard-count self relation, using the existing stats/history."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AbilityInstance, Attack, CardClass, CardDefinition, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, StatReference, StatRelationLayer,
    StatRelationOperand, StatRelationSpec, TriggerSpec, Zone, discarded_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, Draw, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand,
    SetStats, Silence, Summon, Transform)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.engine.zones import CardReference, DiscardCard, DiscardMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='ICC_841'
PATH=Path(__file__).resolve().parents[1]/'data/support/discard-count-attack-basics.json'
PIN='17336a1c3b3a464564fdb1694e635d0b1274999686e1b1b07f73e4d74b466cc2'
REL=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_DISCARD_COUNT,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=1)


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Complete discard-count Attack raw evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']


def first(c,player=None):
    return CardReference.capture(next(c.state.entities[i]for i in c.state.players[player or c.player_id].hand
        if c.state.entities[i].card_id=='a'))


def registry():
    r=Registry('isolated-discard-count-attack-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],keywords=(Keyword.LIFESTEAL,),stat_relations=(REL,),
        metadata=metadata(CardClass.WARLOCK,rarity=Rarity.LEGENDARY,tribes=('undead',))))
    for cid in ('plain','a'):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('b','b',CardType.SPELL,metadata=metadata()))

    def fail(c):raise RuntimeError('deliberate late failure')
    r.register_behavior('late-fault',fail)

    def waiting(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('discard','Discard',(DiscardCard(first(c),c.source_id),)),
            ChoiceOption('fault','Discard then fail',(DiscardCard(first(c),c.source_id),
                InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)

    def observed(c):
        if c.event.player_id!=c.player_id:return ()
        value=c.state.entities[c.state.players[c.player_id].board[0]].attack
        return (GainArmor(c.player_id,value),)

    def discard_wait(c):
        if c.event.player_id!=c.player_id:return ()
        value=c.state.entities[c.state.players[c.player_id].board[0]].attack
        return (RequestChoice(c.player_id,(ChoiceOption('record','Record captured Attack',
            (GainArmor(c.player_id,value),)),),c.source_id),)

    def attack_wait(c):
        if c.event.source_id!=c.state.players[c.player_id].board[0]:return ()
        return waiting(c)

    for name,event,body in (('observer','card_discarded',observed),('waiter','card_discarded',discard_wait),
                            ('attackwatch','attack_declared',attack_wait)):
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=10,
            triggers=(TriggerSpec(event,name),),metadata=metadata()))

    def repeated_reference(c):
        ref=first(c);return (DiscardCard(ref,c.source_id),DiscardCard(ref,c.source_id))

    scripts={
        'discard':lambda c:(DiscardCard(first(c),c.source_id),),
        'enemy.discard':lambda c:(DiscardCard(first(c,3-c.player_id),c.source_id),),
        'many':lambda c:(DiscardMatching(c.player_id,count=2,selection='first',source_id=c.source_id),),
        'repeat.ref':repeated_reference,
        'give':lambda c:(AddToHand(c.player_id,NATIVE),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'draw2':lambda c:(Draw(c.player_id,2,c.source_id),),
        'summon':lambda c:(Summon(c.player_id,NATIVE),),
        'awake':lambda c:(AwakenMinion(c.state.players[c.player_id].board[0]),),
        'hurt.hero':lambda c:(Damage(c.state.players[c.player_id].hero_id,7,c.source_id),),
        'wait':waiting,
        'fault.discard':lambda c:(DiscardCard(first(c),c.source_id),InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    targeted={
        'buff':lambda c:(Buff(c.target_id,attack=3,source_id=c.source_id),),
        'negative':lambda c:(Buff(c.target_id,attack=-2,source_id=c.source_id),),
        'set':lambda c:(SetStats(c.target_id,attack=1,source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,2),),
        'copybase':lambda c:(CopyMinion(c.target_id,2,mode='base'),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'away':lambda c:(Transform(c.target_id,'plain'),),
        'into':lambda c:(Transform(c.target_id,NATIVE),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'sleep':lambda c:(MakeDormant(c.target_id,3),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
    }
    for name,body in {**scripts,**targeted}.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r


class DiscardCountAttackTests(unittest.TestCase):
    def game(self,hand=(),board=(NATIVE,),enemy_hand=(),enemy_board=('plain',),deck=('b',)*5):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy_board,deck=('b',)*5,mana=10,max_mana=10),
        ),seed=48),registry())
    def actor(self,g):return g.state.players[1].board[0]
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def cast(self,g,name,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
        definition=g.registry.card(name)
        return g.apply(PlayCard(player,eid,(self.actor(g)if target is None else target)if definition.requires_target else None))
    def value(self,g,attack,bonus,eid=None):
        e=g.state.entities[self.actor(g)if eid is None else eid]
        self.assertEqual((e.attack,e.conditional_attack),(attack,bonus))
    def rows(self,g,eid):return tuple(a for a in g.state.entities[eid].abilities if a.kind=='stat_relation')
    def choose(self,g,name):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_complete_raw_pin_and_native_metadata(self):
        raw=evidence();card=registry().card(NATIVE)
        original=next(r for r in json.loads((PATH.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if r['id']==NATIVE)
        self.assertEqual(raw,original)
        self.assertEqual((card.cost,card.attack,card.health,card.keywords,card.stat_relations),(5,1,6,(Keyword.LIFESTEAL,),(REL,)))
        self.assertEqual((card.metadata.classes,card.metadata.tribes,card.metadata.rarity),((CardClass.WARLOCK,),('undead',),Rarity.LEGENDARY))
        self.assertIn("card you've discarded",raw['text_en'])

    def test_closed_native_spec_and_no_new_grant_profile(self):
        for fields in ({'operand':'controller_discard_count'},{'amount':0},{'amount':-1},{'amount':True},
                       {'amount':1.0},{'layer':StatRelationLayer.FINAL_ATTACK},{'target':StatReference.HEALTH}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(REL,**fields)
        with self.assertRaises(ValueError):GrantStatRelation(1,REL)
        native=AbilityInstance(1,'stat_relation',origin='printed',source_id=1,stat_relation=REL)
        for fields in ({'origin':'granted'},{'source_id':None},{'expires_turn':1},{'consumed':True}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(native,**fields)

    def test_non_minion_native_face_is_rejected(self):
        for kind in (CardType.SPELL,CardType.WEAPON):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                r=Registry('bad');r.register_card(CardDefinition('bad','bad',kind,stat_relations=(REL,),metadata=metadata()));r.freeze()

    def test_zero_history_native_hand_deck_and_board_share_original_scope(self):
        g=self.game(('discard','a',NATIVE),deck=(NATIVE,))
        native_ids=tuple(e.id for e in g.state.entities.values()if e.card_id==NATIVE)
        for eid in native_ids:self.value(g,1,0,eid)
        self.cast(g,'discard')
        for eid in native_ids:self.value(g,2,1,eid)
        self.portable(g)

    def test_each_actual_discard_updates_without_baking_permanent_stats(self):
        g=self.game(('many','a','a'));source=self.actor(g);self.cast(g,'many');self.value(g,3,2)
        e=g.state.entities[source];self.assertEqual((e.base_attack,e.attack_bonus,e.enchantments),(1,0,[]))
        self.assertEqual(len(discarded_cards(g.state,1)),2);self.portable(g)

    def test_obtained_after_prior_discards_reads_full_game_history(self):
        g=self.game(('discard','a','give'),board=());self.cast(g,'discard');self.cast(g,'give')
        eid=g.state.players[1].hand[-1];self.value(g,2,1,eid);self.assertEqual(g.state.entities[eid].card_id,NATIVE);self.portable(g)

    def test_draw_and_manual_play_reuse_native_count(self):
        g=self.game(('discard','a','draw'),board=(),deck=(NATIVE,));self.cast(g,'discard');self.cast(g,'draw')
        eid=g.state.players[1].hand[-1];self.value(g,2,1,eid);g.apply(PlayCard(1,eid));self.value(g,2,1,eid)
        self.assertEqual(len(self.rows(g,eid)),1);self.portable(g)

    def test_direct_summon_uses_current_existing_history(self):
        g=self.game(('discard','a','summon'),board=());self.cast(g,'discard');self.cast(g,'summon');self.value(g,2,1);self.portable(g)

    def test_opponent_discard_only_changes_its_controller_count(self):
        g=self.game(('enemy.discard','discard','a'),enemy_hand=('a',),enemy_board=(NATIVE,))
        enemy=g.state.players[2].board[0];self.cast(g,'enemy.discard');self.value(g,1,0);self.value(g,2,1,enemy)
        self.cast(g,'discard');self.value(g,2,1);self.value(g,2,1,enemy);self.portable(g)

    def test_original_card_kind_does_not_limit_history_count(self):
        g=self.game(('many','a','b'));self.cast(g,'many');self.value(g,3,2)
        self.assertEqual([r.kind for r in discarded_cards(g.state,1)],[CardType.MINION,CardType.SPELL]);self.portable(g)

    def test_reused_stale_reference_does_not_add_second_count(self):
        g=self.game(('repeat.ref','a'));self.cast(g,'repeat.ref');self.value(g,2,1)
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),1);self.portable(g)

    def test_burn_play_and_death_do_not_increase_count(self):
        g=self.game(('draw2','kill')+('a',)*8,deck=('a','a'));self.cast(g,'draw2');self.value(g,1,0)
        plain=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='a');g.apply(PlayCard(1,plain))
        self.cast(g,'kill',plain);self.value(g,1,0);self.assertEqual(discarded_cards(g.state,1),());self.portable(g)

    def test_original_numeric_set_and_add_keep_count_as_derived_layer(self):
        g=self.game(('discard','a','buff','set','discard','a'));self.cast(g,'discard');self.cast(g,'buff');self.value(g,5,1)
        self.cast(g,'set');self.value(g,2,1);self.cast(g,'discard');self.value(g,3,2);self.portable(g)

    def test_zero_floor_is_after_count_contribution(self):
        g=self.game(('negative','discard','a','discard','a'));self.cast(g,'negative');self.value(g,0,0)
        self.cast(g,'discard');self.value(g,0,1);self.cast(g,'discard');self.value(g,1,2);self.portable(g)

    def test_silence_removes_count_relation_and_future_growth(self):
        g=self.game(('discard','a','silence','discard','a'));self.cast(g,'discard');self.cast(g,'silence');self.value(g,1,0)
        self.cast(g,'discard');self.value(g,1,0);self.assertEqual(self.rows(g,self.actor(g)),());self.portable(g)

    def test_current_copy_reads_destination_count_and_keeps_native_provenance(self):
        g=self.game(('discard','a','copy'));source=self.actor(g);self.cast(g,'discard');self.cast(g,'copy')
        dest=g.state.players[2].board[-1];self.value(g,1,0,dest);self.value(g,2,1,source)
        self.assertEqual(self.rows(g,dest)[0].source_id,source);self.assertNotEqual(self.rows(g,dest)[0].id,self.rows(g,source)[0].id);self.portable(g)

    def test_silenced_current_copy_keeps_removed_relation(self):
        g=self.game(('discard','a','silence','copy'));self.cast(g,'discard');self.cast(g,'silence');self.cast(g,'copy')
        dest=g.state.players[2].board[-1];self.value(g,1,0,dest);self.assertEqual(self.rows(g,dest),());self.portable(g)

    def test_base_copy_reinstalls_native_relation_in_destination(self):
        g=self.game(('enemy.discard','silence','copybase'),enemy_hand=('a',));self.cast(g,'enemy.discard');self.cast(g,'silence');self.cast(g,'copybase')
        dest=g.state.players[2].board[-1];self.value(g,2,1,dest);self.assertEqual(len(self.rows(g,dest)),1);self.portable(g)

    def test_bounce_reset_and_replay_use_same_history(self):
        g=self.game(('discard','a','silence','bounce'));source=self.actor(g);self.cast(g,'discard');self.cast(g,'silence');self.cast(g,'bounce')
        self.value(g,2,1,source);self.assertEqual(g.state.entities[source].zone,Zone.HAND);g.apply(PlayCard(1,source));self.value(g,2,1);self.portable(g)

    def test_transform_away_and_into_use_original_native_installation(self):
        g=self.game(('discard','a','away','into'));self.cast(g,'discard');self.cast(g,'away');self.value(g,1,0)
        self.cast(g,'into');self.value(g,2,1);self.portable(g)

    def test_control_change_reads_new_controller_without_rewriting_history(self):
        g=self.game(('discard','a','control'));source=self.actor(g);self.cast(g,'discard');before=discarded_cards(g.state,1);self.cast(g,'control')
        self.value(g,1,0,source);self.assertEqual((g.state.entities[source].owner,g.state.entities[source].controller),(1,2))
        self.assertEqual(discarded_cards(g.state,1),before);self.portable(g)

    def test_dormant_contribution_is_absent_then_recomputed_on_awake(self):
        g=self.game(('sleep','discard','a','awake'));self.cast(g,'sleep');self.cast(g,'discard');self.value(g,1,0)
        self.cast(g,'awake');self.value(g,2,1);self.portable(g)

    def test_death_record_keeps_original_attack_and_not_future_count(self):
        g=self.game(('discard','a','kill','discard','a'));source=self.actor(g);self.cast(g,'discard');self.cast(g,'kill',source)
        row=next(r for r in g.state.death_history if r.entity_id==source);self.assertEqual(row.attack,2)
        self.assertEqual(next(a.stat_relation for a in row.abilities if a.kind=='stat_relation'),REL)
        self.cast(g,'discard');self.value(g,3,2,source);self.assertEqual(next(r.attack for r in g.state.death_history if r.entity_id==source),2);self.portable(g)

    def test_real_native_attack_and_existing_lifesteal_use_latest_value(self):
        g=self.game(('discard','a','hurt.hero'));self.cast(g,'discard');self.cast(g,'hurt.hero')
        g.apply(Attack(1,self.actor(g),self.hero(g,2).id))
        self.assertEqual((self.hero(g,2).damage,self.hero(g).damage),(2,5));self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,1);self.portable(g)

    def test_original_discard_listener_captures_updated_attack_each_time(self):
        g=self.game(('many','a','a'),board=(NATIVE,'observer'));self.cast(g,'many')
        self.value(g,3,2);self.assertEqual(self.hero(g).armor,5);self.portable(g)

    def test_discard_listener_waiting_states_resume_with_original_count(self):
        g=self.game(('many','a','a'),board=(NATIVE,'waiter'));self.cast(g,'many');self.value(g,2,1)
        h=self.portable(g);clone=g.clone()
        for branch in (g,h,clone):
            self.choose(branch,'record');self.value(branch,3,2);self.assertEqual(self.hero(branch).armor,2)
            self.assertIsNotNone(branch.state.pending_choice);self.portable(branch)
            self.choose(branch,'record');self.assertIsNone(branch.state.pending_choice);self.assertEqual(self.hero(branch).armor,5);self.portable(branch)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_declared_wait_rechecks_count_before_combat_damage_is_prepared(self):
        g=self.game(('a',),board=(NATIVE,'attackwatch'));source=self.actor(g);g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g)
        for branch in (g,h):
            self.choose(branch,'discard');self.value(branch,2,1);self.assertEqual(self.hero(branch,2).damage,2)
            self.assertEqual(branch.state.entities[source].attacks_this_turn,1);self.portable(branch)
        self.assertEqual(g.snapshot(),h.snapshot())

    def test_immediate_and_waiting_failures_roll_back_history_and_cache(self):
        g=self.game(('fault.discard','a'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault.discard')
        self.assertEqual(g.snapshot(),before);self.portable(g)
        g=self.game(('wait','a'));self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_queries_and_player_interfaces_hide_internal_relation_and_history(self):
        g=self.game(('discard','a'),enemy_hand=(NATIVE,));self.cast(g,'discard');before=g.snapshot()
        for _ in range(3):
            self.assertEqual(conditional_attack(g.state,g.state.entities[self.actor(g)]),1)
            public=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
            for key in ('conditional_attack','controller_discard_count','stat_relation','discard_history','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_captured_state_keeps_original_history_derived_attack(self):
        g=self.game(('discard','a','discard','a'));source=self.actor(g);self.cast(g,'discard');context=RuleContext(g.state,source,1)
        self.cast(g,'discard');codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        saved=codec.encode(context);restored=codec.decode(saved);self.assertEqual(restored.state.entities[source].conditional_attack,1)
        self.assertEqual(len(restored.state.discard_history),1);self.value(g,3,2)
        for value in (0,2,True,1.0,None):
            bad=deepcopy(saved);bad['fields']['state']['state']['entities'][str(source)]['conditional_attack']=value
            with self.subTest(value=value),self.assertRaises(ValueError):codec.decode(bad)
        self.portable(g)

    def test_rehashed_cache_and_native_identity_tampering_are_rejected(self):
        g=self.game(('discard','a'));self.cast(g,'discard');snap=g.snapshot();source=self.actor(g)
        for value in (0,2,True,1.0,-1,None,'1'):
            bad=deepcopy(snap);bad['state']['entities'][str(source)]['conditional_attack']=value
            with self.subTest(value=value):self.reject(bad)
        bad=deepcopy(snap);del bad['state']['entities'][str(source)]['conditional_attack'];self.reject(bad)
        idx=next(i for i,a in enumerate(snap['state']['entities'][str(source)]['abilities'])if a['kind']=='stat_relation')
        for field,value in (('operand','controller_has_weapon'),('amount',2),('layer','final_attack')):
            bad=deepcopy(snap);bad['state']['entities'][str(source)]['abilities'][idx]['stat_relation'][field]=value
            with self.subTest(field=field):self.reject(bad)
        bad=deepcopy(snap);row=deepcopy(bad['state']['entities'][str(source)]['abilities'][idx]);row['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1
        bad['state']['entities'][str(source)]['abilities'].append(row);self.reject(bad)

    def test_current_protocol_and_all_old_schema_rejection(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],265)
        self.assertEqual(snap['ruleset']['id'],'prototype-v302');self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (*range(1,218),True,194.0,217):
            bad=deepcopy(snap);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        self.portable(g)


if __name__=='__main__':unittest.main()
