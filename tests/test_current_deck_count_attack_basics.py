"""One native continuous self Attack condition; reuse the existing stat layer."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AbilityInstance, Attack, CardClass, CardDefinition, CardType,
    DeckSpec, Game, IllegalAction, Keyword, MatchSetup, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, StatReference,
    StatRelationLayer, StatRelationOperand, StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, Draw, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand,
    SetStats, Silence, Summon, Transform)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.engine.zones import AddToDeck, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='JAIL_311'
PATH=Path(__file__).resolve().parents[1]/'data/support/current-deck-count-attack-basics.json'
PIN='b1d1665c16973854d6ae6d040bdff130d8068525672b395fcc12d9b13e5fdbc4'
REL=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_DECK_COUNT,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=5,card_count=25,comparison='at_least')


def evidence():
    support=json.loads(PATH.read_bytes())
    if canonical_digest(support)!=PIN:raise ValueError('Complete native deck-count Attack evidence changed')
    row=support['records'][0]
    if row['id']!=NATIVE or canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Complete native card evidence changed')
    return row['data']


def registry():
    r=opening_registry();raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],keywords=(Keyword.TAUNT,),stat_relations=(REL,),
        metadata=metadata(CardClass.WARRIOR,rarity=Rarity.COMMON,tribes=())))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('no_meta','Known without class metadata',CardType.MINION,health=1))
    r.register_behavior('nop',lambda c:())
    r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=1,durability=1,metadata=metadata()))
    r.register_card(CardDefinition('location','Location',CardType.LOCATION,durability=1,on_use='nop',metadata=metadata()))
    r.register_card(CardDefinition('spell','Spell',CardType.SPELL,metadata=metadata()))

    def fail(c):raise RuntimeError('deliberate late deck-count failure')
    r.register_behavior('late-fault',fail)

    def waiting(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('draw','Draw',(Draw(c.player_id,source_id=c.source_id),)),
            ChoiceOption('fault','Draw then fail',(Draw(c.player_id,source_id=c.source_id),
                InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)

    def observe(c):
        if c.event.player_id!=c.player_id:return ()
        return (GainArmor(c.player_id,c.state.entities[c.state.players[c.player_id].board[0]].attack),)

    def wait_after_draw(c):
        if c.event.player_id!=c.player_id:return ()
        value=c.state.entities[c.state.players[c.player_id].board[0]].attack
        return (RequestChoice(c.player_id,(ChoiceOption('record','Record captured Attack',
            (GainArmor(c.player_id,value),)),),c.source_id),)

    def wait_attack(c):
        if c.event.source_id!=c.state.players[c.player_id].board[0]:return ()
        return waiting(c)

    for name,event,body in (('observer','card_drawn',observe),('waiter','card_drawn',wait_after_draw),
                            ('attackwatch','attack_declared',wait_attack)):
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=10,
            triggers=(TriggerSpec(event,name),),metadata=metadata()))

    scripts={
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'draw2':lambda c:(Draw(c.player_id,2,c.source_id),),
        'enemy.draw':lambda c:(Draw(3-c.player_id,source_id=c.source_id),),
        'add':lambda c:(AddToDeck(c.player_id,'plain','random',c.source_id),),
        'clear':lambda c:(DestroyDeckMatching(c.player_id,count=70,reveal=False),),
        'summon':lambda c:(Summon(c.player_id,NATIVE),),
        'awake':lambda c:(AwakenMinion(c.state.players[c.player_id].board[0]),),
        'wait':waiting,
        'fault.draw':lambda c:(Draw(c.player_id,source_id=c.source_id),
                              InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    targeted={
        'buff':lambda c:(Buff(c.target_id,attack=3,source_id=c.source_id),),
        'negative':lambda c:(Buff(c.target_id,attack=-4,source_id=c.source_id),),
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


class CurrentDeckCountAttackTests(unittest.TestCase):
    def game(self,hand=(),board=(NATIVE,),count=25,enemy_count=24,enemy_board=('plain',),deck=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*count if deck is None else deck,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy_board,deck=('plain',)*enemy_count,mana=10,max_mana=10),
        ),seed=48),registry())
    def actor(self,g):return g.state.players[1].board[0]
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def cast(self,g,name,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        target=(self.actor(g)if target is None else target)if g.registry.card(name).requires_target else None
        return g.apply(PlayCard(1,eid,target))
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
        original=next(r for r in json.loads((PATH.parents[1]/'extracted/cards.json').read_bytes())if r['id']==NATIVE)
        self.assertEqual(raw,original)
        self.assertEqual((card.cost,card.attack,card.health,card.keywords,card.stat_relations),
                         (4,2,7,(Keyword.TAUNT,),(REL,)))
        self.assertEqual((card.metadata.classes,card.metadata.tribes,card.metadata.rarity),
                         ((CardClass.WARRIOR,),(),Rarity.COMMON))
        self.assertIn('25 or more cards',raw['text_en'])

    def test_strict_closed_spec_and_old_operands_keep_no_threshold(self):
        for fields in ({'operand':'controller_deck_count'},{'amount':0},{'amount':-1},{'amount':True},
                       {'amount':1.0},{'layer':StatRelationLayer.FINAL_ATTACK},{'target':StatReference.HEALTH},
                       {'card_count':None},{'card_count':True},{'card_count':-1},{'card_count':25.0},
                       {'comparison':None},{'comparison':'greater'},{'comparison':True}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(REL,**fields)
        for operand in (StatRelationOperand.SELF_CURRENT_HEALTH,StatRelationOperand.SELF_DAMAGED,
                        StatRelationOperand.CONTROLLER_HAS_WEAPON,StatRelationOperand.CONTROLLER_DISCARD_COUNT):
            old=StatRelationSpec() if operand==StatRelationOperand.SELF_CURRENT_HEALTH else StatRelationSpec(
                operand=operand,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=1)
            self.assertIsNone(old.card_count);self.assertIsNone(old.comparison)
            for field,value in (('card_count',25),('comparison','at_least')):
                with self.subTest(operand=operand,field=field),self.assertRaises(ValueError):replace(old,**{field:value})
        low=replace(REL,card_count=0,comparison='at_most');self.assertEqual(low.card_count,0)
        self.assertEqual(FrameCodec(self.game().mechanics,registry()).decode(
            FrameCodec(self.game().mechanics,registry()).encode(REL)),REL)

    def test_printed_lifecycle_carrier_duplicates_and_new_grants_are_guarded(self):
        with self.assertRaises(ValueError):GrantStatRelation(1,REL)
        native=AbilityInstance(1,'stat_relation',origin='printed',source_id=1,stat_relation=REL)
        for fields in ({'origin':'granted'},{'source_id':None},{'expires_turn':1},{'consumed':True},
                       {'remove_on_silence':False},{'magnetic_id':1}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(native,**fields)
        for kind in (CardType.SPELL,CardType.WEAPON):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                r=Registry('bad');r.register_card(CardDefinition('bad','bad',kind,stat_relations=(REL,)));r.freeze()
        with self.assertRaises(ValueError):
            r=Registry('duplicate');r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,stat_relations=(REL,REL)));r.freeze()

    def test_24_25_26_inclusive_threshold_uses_current_physical_slots(self):
        for count,expected in ((24,(2,0)),(25,(7,5)),(26,(7,5))):
            with self.subTest(count=count):
                g=self.game(count=count);self.value(g,*expected);self.portable(g)
                self.assertIsNone(g.state.opening)

    def test_all_card_kinds_duplicates_and_no_metadata_count_equally(self):
        g=self.game(deck=('weapon','location','spell','no_meta')+('plain',)*21)
        self.value(g,7,5);self.assertEqual(len(g.state.players[1].deck),25);self.portable(g)

    def test_hand_deck_and_board_use_the_existing_active_display_policy(self):
        g=self.game((NATIVE,),deck=(NATIVE,)+('plain',)*24)
        ids=tuple(e.id for e in g.state.entities.values()if e.card_id==NATIVE)
        self.assertEqual(len(ids),3)
        for eid in ids:self.value(g,7,5,eid)
        self.portable(g)

    def test_drawing_the_native_reprices_hand_then_manual_play(self):
        g=self.game(('draw',),board=(),deck=(NATIVE,)+('plain',)*24)
        eid=g.state.players[1].deck[0];self.value(g,7,5,eid);self.cast(g,'draw');self.value(g,2,0,eid)
        g.apply(PlayCard(1,eid));self.value(g,2,0,eid)
        self.assertEqual(g.state.entities[eid].attacks_this_turn,0);self.portable(g)

    def test_draw_shuffle_and_clear_switch_without_permanent_stacking(self):
        g=self.game(('draw','add','add','clear'));e=g.state.entities[self.actor(g)]
        self.cast(g,'draw');self.value(g,2,0);self.cast(g,'add');self.value(g,7,5)
        self.cast(g,'add');self.value(g,7,5);self.cast(g,'clear');self.value(g,2,0)
        current=g.state.entities[e.id]
        self.assertEqual((current.base_attack,current.attack_bonus,current.enchantments),(2,0,[]));self.portable(g)

    def test_opponent_draw_uses_only_its_own_current_controller_deck(self):
        g=self.game(('enemy.draw','draw'),enemy_count=25,enemy_board=(NATIVE,))
        enemy=g.state.players[2].board[0];self.cast(g,'enemy.draw')
        self.value(g,7,5);self.value(g,2,0,enemy)
        self.cast(g,'draw');self.value(g,2,0);self.value(g,2,0,enemy);self.portable(g)

    def test_numeric_set_and_add_use_the_existing_conditional_layer(self):
        g=self.game(('buff','set','draw'));self.cast(g,'buff');self.value(g,10,5)
        self.cast(g,'set');self.value(g,6,5);self.cast(g,'draw');self.value(g,1,0);self.portable(g)

    def test_zero_floor_follows_conditional_contribution(self):
        g=self.game(('negative','draw'));self.cast(g,'negative');self.value(g,3,5)
        self.cast(g,'draw');self.value(g,0,0);self.portable(g)

    def test_silence_removes_relation_and_future_threshold_changes(self):
        g=self.game(('silence','draw','add'));self.cast(g,'silence');self.value(g,2,0)
        self.cast(g,'draw');self.cast(g,'add');self.value(g,2,0)
        self.assertEqual(self.rows(g,self.actor(g)),());self.portable(g)

    def test_current_copy_recomputes_destination_and_keeps_native_provenance(self):
        g=self.game(('copy',));source=self.actor(g);self.cast(g,'copy')
        dest=g.state.players[2].board[-1];self.value(g,2,0,dest);self.value(g,7,5,source)
        self.assertEqual(self.rows(g,dest)[0].source_id,source)
        self.assertNotEqual(self.rows(g,dest)[0].id,self.rows(g,source)[0].id);self.portable(g)

    def test_silenced_current_copy_stays_silenced_and_base_copy_reinstalls(self):
        g=self.game(('silence','copy','copybase'),enemy_count=25);self.cast(g,'silence');self.cast(g,'copy')
        current=g.state.players[2].board[-1];self.value(g,2,0,current);self.assertEqual(self.rows(g,current),())
        self.cast(g,'copybase');base=g.state.players[2].board[-1];self.value(g,7,5,base)
        self.assertEqual(len(self.rows(g,base)),1);self.portable(g)

    def test_bounce_reset_and_replay_recompute_current_deck(self):
        g=self.game(('silence','bounce','draw'));source=self.actor(g)
        self.cast(g,'silence');self.cast(g,'bounce');self.value(g,7,5,source)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.cast(g,'draw');g.apply(PlayCard(1,source));self.value(g,2,0,source);self.portable(g)

    def test_transform_away_and_into_install_original_native_relation(self):
        g=self.game(('away','into','draw'));self.cast(g,'away');self.value(g,1,0)
        self.cast(g,'into');self.value(g,7,5);self.cast(g,'draw');self.value(g,2,0);self.portable(g)

    def test_control_change_immediately_reads_new_controller_deck(self):
        g=self.game(('control','enemy.draw'),count=24,enemy_count=25)
        source=self.actor(g);self.value(g,2,0);self.cast(g,'control')
        self.value(g,7,5,source)
        self.assertEqual((g.state.entities[source].owner,g.state.entities[source].controller),(1,2))
        self.cast(g,'enemy.draw');self.value(g,2,0,source);self.portable(g)

    def test_dormancy_suppresses_then_awake_reads_current_deck(self):
        g=self.game(('sleep','draw','awake','add'));self.cast(g,'sleep');self.value(g,2,0)
        self.cast(g,'draw');self.cast(g,'awake');self.value(g,2,0)
        self.cast(g,'add');self.value(g,7,5);self.portable(g)

    def test_death_record_retains_original_attack_despite_later_deck_change(self):
        g=self.game(('kill','draw'));source=self.actor(g);self.cast(g,'kill',source)
        row=next(r for r in g.state.death_history if r.entity_id==source);self.assertEqual(row.attack,7)
        self.assertEqual(next(a.stat_relation for a in row.abilities if a.kind=='stat_relation'),REL)
        self.cast(g,'draw');self.value(g,2,0,source)
        self.assertEqual(next(r.attack for r in g.state.death_history if r.entity_id==source),7);self.portable(g)

    def test_native_combat_and_taunt_use_latest_visible_attack_without_refund(self):
        g=self.game(('draw','add'));source=self.actor(g)
        g.apply(Attack(1,source,self.hero(g,2).id));self.assertEqual(self.hero(g,2).damage,7)
        self.cast(g,'draw');self.cast(g,'add');self.value(g,7,5)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.hero(g,2).id))
        enemy=self.game(enemy_board=(NATIVE,),enemy_count=25)
        with self.assertRaises(IllegalAction):enemy.apply(Attack(1,self.actor(enemy),self.hero(enemy,2).id))
        self.portable(g);self.portable(enemy)

    def test_manual_play_and_summon_install_once_without_charge(self):
        g=self.game((NATIVE,'summon'),board=())
        eid=g.state.players[1].hand[0];g.apply(PlayCard(1,eid));self.value(g,7,5,eid)
        self.cast(g,'summon');other=g.state.players[1].board[-1];self.value(g,7,5,other)
        for source in (eid,other):
            self.assertEqual(len(self.rows(g,source)),1)
            with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.hero(g,2).id))
        self.portable(g)

    def test_draw_listeners_capture_updated_attack_at_each_event(self):
        g=self.game(('draw2',),board=(NATIVE,'observer'),count=26);self.cast(g,'draw2')
        self.value(g,2,0);self.assertEqual(self.hero(g).armor,9);self.portable(g)

    def test_two_draw_waiting_contexts_restore_clone_and_replay_each_original_count(self):
        g=self.game(('draw2',),board=(NATIVE,'waiter'),count=26);self.cast(g,'draw2');self.value(g,7,5)
        h=self.portable(g);clone=g.clone()
        for branch in (g,h,clone):
            self.choose(branch,'record');self.value(branch,2,0);self.assertEqual(self.hero(branch).armor,7)
            self.assertIsNotNone(branch.state.pending_choice);self.portable(branch)
            self.choose(branch,'record');self.assertIsNone(branch.state.pending_choice)
            self.assertEqual(self.hero(branch).armor,9);self.portable(branch)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_attack_declared_wait_draws_before_preparing_damage(self):
        g=self.game(board=(NATIVE,'attackwatch'));source=self.actor(g)
        g.apply(Attack(1,source,self.hero(g,2).id));self.assertIsNotNone(g.state.pending_choice)
        h=self.portable(g)
        for branch in (g,h):
            self.choose(branch,'draw');self.value(branch,2,0);self.assertEqual(self.hero(branch,2).damage,2)
            self.assertEqual(branch.state.entities[source].attacks_this_turn,1);self.portable(branch)
        self.assertEqual(g.snapshot(),h.snapshot())

    def test_immediate_and_waiting_failures_roll_back_deck_and_cache(self):
        g=self.game(('fault.draw',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault.draw')
        self.assertEqual(g.snapshot(),before);self.portable(g)
        g=self.game(('wait',));self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_queries_and_public_commands_hide_private_relation_and_inventory(self):
        g=self.game(('draw',));before=g.snapshot()
        for _ in range(3):
            self.assertEqual(conditional_attack(g.state,g.state.entities[self.actor(g)]),5)
            public=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
            for key in ('conditional_attack','controller_deck_count','stat_relation','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
            self.assertNotIn('"deck":',public)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_captured_state_validates_its_own_deck_not_today(self):
        g=self.game(('draw',));source=self.actor(g);context=RuleContext(g.state,source,1);self.cast(g,'draw')
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        saved=codec.encode(context);restored=codec.decode(saved)
        self.assertEqual(len(restored.state.players[1].deck),25)
        self.assertEqual(restored.state.entities[source].conditional_attack,5);self.value(g,2,0)
        for value in (0,6,True,5.0,None):
            bad=deepcopy(saved);bad['fields']['state']['state']['entities'][str(source)]['conditional_attack']=value
            with self.subTest(value=value),self.assertRaises(ValueError):codec.decode(bad)
        self.portable(g)

    def test_rehashed_wire_rejects_stale_cache_and_forged_native_condition(self):
        g=self.game();snap=g.snapshot();source=self.actor(g)
        for value in (0,6,True,5.0,-1,None,'5'):
            bad=deepcopy(snap);bad['state']['entities'][str(source)]['conditional_attack']=value
            with self.subTest(value=value):self.reject(bad)
        bad=deepcopy(snap);del bad['state']['entities'][str(source)]['conditional_attack'];self.reject(bad)
        idx=next(i for i,a in enumerate(snap['state']['entities'][str(source)]['abilities'])if a['kind']=='stat_relation')
        for field,value in (('card_count',24),('comparison','at_most'),('operand','controller_has_weapon'),
                            ('amount',6),('card_count',True),('comparison',None),('layer','final_attack')):
            bad=deepcopy(snap);bad['state']['entities'][str(source)]['abilities'][idx]['stat_relation'][field]=value
            with self.subTest(field=field):self.reject(bad)
        for field in ('card_count','comparison'):
            bad=deepcopy(snap);del bad['state']['entities'][str(source)]['abilities'][idx]['stat_relation'][field]
            with self.subTest(missing=field):self.reject(bad)
        bad=deepcopy(snap);row=deepcopy(bad['state']['entities'][str(source)]['abilities'][idx])
        row['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1
        bad['state']['entities'][str(source)]['abilities'].append(row);self.reject(bad)

    def test_constructed_thirty_cards_current_count_and_mulligan_are_distinct(self):
        r=registry();own=(NATIVE,)+tuple(f'card.{i}' for i in range(1,30))
        other=tuple(f'card.{i}' for i in range(1,31))
        g=Game.from_decks(MatchSetup((DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,own),
            DeckSpec('mage.hero','mage.power',CardClass.MAGE,other)),policy(r),'coin',85,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        eid=next(e.id for e in g.state.entities.values()if e.card_id==NATIVE)
        self.assertEqual(len(g.state.players[1].original_deck),30)
        self.assertEqual(len(g.state.players[1].deck),26);self.value(g,7,5,eid);self.portable(g)

    def test_current_protocol_and_strict_old_schema_rejection(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],266)
        self.assertEqual(snap['ruleset']['id'],'prototype-v302')
        self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (*range(1,218),True,218.0,None,'218'):
            bad=deepcopy(snap);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        self.portable(g)


if __name__=='__main__':unittest.main()

