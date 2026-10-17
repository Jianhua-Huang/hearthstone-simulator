"""Fixed board-copy stats are installed before ordinary entry and its observers."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AuraSpec,CardDefinition,CardType,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,
    SummonCause,SummonStats,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,CopyMinion,Damage,Destroy,
    GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='UNG_022'
PIN='adf5039844f0cb1a8de75aea3ff40a2cae73f214fa378f510c6c440751f4739c'
FIXED=SummonStats(1,1)


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/board-copy-entry-stats-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Board copy evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Complete raw copy source changed')
    return data


def registry():
    r=Registry('isolated-board-copy-entry-stats-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('body','Body',CardType.MINION,attack=4,health=7,
        keywords=(Keyword.TAUNT,),battlecry='cry',metadata=metadata(tribes=())))
    r.register_behavior('cry',lambda c:(GainArmor(c.player_id,5),))
    raw=evidence()['records'][0]['data']
    r.register_behavior('mirage',lambda c:() if c.target_id is None else (
        CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c),stats=FIXED),))
    r.register_card(CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry='mirage',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,)),metadata=metadata_from_record(raw)))
    def fixed(c,mode='current',player=1,position=None,stats=FIXED,cause=False):
        return (CopyMinion(c.target_id,player,position,mode,SummonCause.capture(c) if cause else None,stats),)
    def wait(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Copy',fixed(c)),
            ChoiceOption('fault','Copy then fail',(*fixed(c),InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)
    scripts={
        'copy':lambda c:fixed(c),
        'base':lambda c:fixed(c,'base'),
        'raw':lambda c:fixed(c,stats=None),
        'attack-only':lambda c:fixed(c,stats=SummonStats(2,None)),
        'health-only':lambda c:fixed(c,stats=SummonStats(None,2)),
        'enemy-copy':lambda c:fixed(c,player=2),
        'position':lambda c:fixed(c,position=0),
        'attributed':lambda c:fixed(c,cause=True),
        'prep':lambda c:(Buff(c.target_id,3,2,c.source_id),Damage(c.target_id,3,c.source_id)),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'dead-copy':lambda c:(Destroy(c.target_id,c.source_id),*fixed(c)),
        'wait':wait,
        'fault':lambda c:(*fixed(c),InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    for name,body in scripts.items():
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            targeting=TargetSpec(kinds=(CardType.MINION,)),metadata=metadata(tribes=())))
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.fixed-copy'),))
    def observe(c):
        target=c.state.entities[c.event.target_id]
        if target.card_id!='body':return ()
        return (GainArmor(2,target.attack*10+target.health),)
    r.register_behavior('observe',observe)
    r.register_card(CardDefinition('observer','Entry observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('minion_summoned','observe'),),metadata=metadata(tribes=())))
    r.register_behavior('entry-wait',lambda c:() if c.state.entities[c.event.target_id].card_id!='body' else (
        RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id),))
    r.register_card(CardDefinition('waiter','Entry wait',CardType.MINION,health=3,
        triggers=(TriggerSpec('minion_summoned','entry-wait'),),metadata=metadata(tribes=())))
    r.register_card(CardDefinition('aura','Aura',CardType.MINION,health=3,
        auras=(AuraSpec(attack=2,health=3),),metadata=metadata(tribes=())))
    return r


class BoardCopyEntryStatsBasicsTests(unittest.TestCase):
    def game(self,hand=(),board=('body',),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('body',)*4,max_mana=10,mana=10),
            PlayerSetup('hero',board=enemy,deck=('body',)*4,max_mana=10,mana=10)),seed=61),registry())
    def target(self,g,p=1):return next(i for i in g.state.players[p].board if g.state.entities[i].card_id=='body')
    def play(self,g,name,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid,target))
    def copy(self,g,p=1):return next(g.state.entities[i] for i in reversed(g.state.players[p].board)
        if g.state.entities[i].card_id=='body' and g.state.entities[i].origin_entity_id is not None)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def stats(self,entity,attack,health,damage=0):
        self.assertEqual((entity.attack,entity.max_health,entity.damage),(attack,health,damage))

    def test_complete_raw_pin_and_one_necessary_source(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD])
        self.assertEqual((card.cost,card.attack,card.health),(3,2,3))
        self.assertEqual(card.metadata.classes,('priest',));self.assertEqual(card.targeting.relation,'any')

    def test_typed_optional_stats_and_positional_cause_compatibility(self):
        self.assertIsNone(CopyMinion(1,1).stats)
        self.assertEqual(CopyMinion(1,1,None,'base',None,FIXED).stats,FIXED)
        for value in ({'attack':1,'health':1},True,(1,1)):
            with self.subTest(value=value),self.assertRaises(ValueError):CopyMinion(1,1,stats=value)
        self.assertEqual(SummonStats(1,0).health,0)
        with self.assertRaises(ValueError):SummonStats(1,-1)
        with self.assertRaises(ValueError):SummonStats(True,1)

    def test_real_battlecry_copies_either_side_without_replaying_source_battlecry(self):
        for side in (1,2):
            with self.subTest(side=side):
                g=self.game((CARD,),board=('body',) if side==1 else (),enemy=('body',) if side==2 else ())
                source=self.target(g,side);self.play(g,CARD,source);copied=self.copy(g)
                self.stats(copied,1,1);self.assertEqual(copied.origin_entity_id,source)
                self.assertEqual((copied.owner,copied.controller),(1,1));self.assertNotEqual(copied.id,source)
                self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
                self.portable(g)

    def test_real_optional_battlecry_with_no_minion_and_hero_target_rejection(self):
        g=self.game((CARD,),board=());before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CARD,g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before);self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_fixed_current_copy_retains_local_abilities_but_resets_damage(self):
        g=self.game(('prep','copy'));source=self.target(g);self.play(g,'prep',source);self.play(g,'copy',source)
        copied=self.copy(g);self.stats(copied,1,1);self.stats(g.state.entities[source],7,9,3)
        self.assertIn(Keyword.TAUNT,copied.keywords)
        self.assertTrue(any(e.label=='summon_stats' for e in copied.enchantments));self.portable(g)

    def test_fixed_base_copy_rebuilds_printed_material_without_source_buff(self):
        g=self.game(('prep','base'));source=self.target(g);self.play(g,'prep',source);self.play(g,'base',source)
        copied=self.copy(g);self.stats(copied,1,1)
        self.assertEqual((copied.base_attack,copied.base_health),(4,7))
        self.assertEqual(len(copied.enchantments),1);self.assertIn(Keyword.TAUNT,copied.keywords);self.portable(g)

    def test_attribute_overrides_are_independent_and_only_health_resets_damage(self):
        for name,attack,health,damage in (('attack-only',2,9,3),('health-only',7,2,0)):
            with self.subTest(name=name):
                g=self.game(('prep',name));source=self.target(g);self.play(g,'prep',source);self.play(g,name,source)
                self.stats(self.copy(g),attack,health,damage);self.portable(g)

    def test_default_current_copy_preserves_previous_damage_and_stats(self):
        g=self.game(('prep','raw'));source=self.target(g);self.play(g,'prep',source);self.play(g,'raw',source)
        self.stats(self.copy(g),7,9,3);self.assertFalse(any(e.label=='summon_stats' for e in self.copy(g).enchantments));self.portable(g)

    def test_entry_observer_sees_fixed_stats_before_its_own_checkpoint(self):
        g=self.game(('prep','copy'),board=('body','observer'));source=self.target(g)
        self.play(g,'prep',source);self.play(g,'copy',source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,11);self.portable(g)

    def test_new_recipient_auras_apply_after_local_fixed_layer(self):
        g=self.game(('enemy-copy',),enemy=('aura',));source=self.target(g);self.play(g,'enemy-copy',source)
        self.stats(self.copy(g,2),3,4);self.stats(g.state.entities[source],4,7);self.portable(g)

    def test_silence_removes_fixed_copy_enchantment_without_rewriting_base(self):
        g=self.game(('copy','silence'));self.play(g,'copy',self.target(g));copied=self.copy(g)
        self.play(g,'silence',copied.id);self.stats(g.state.entities[copied.id],4,7);self.portable(g)

    def test_return_resets_fixed_copy_to_its_original_printed_card(self):
        g=self.game(('copy','bounce'));self.play(g,'copy',self.target(g));eid=self.copy(g).id
        self.play(g,'bounce',eid);entity=g.state.entities[eid]
        self.assertEqual(entity.zone,Zone.HAND);self.stats(entity,4,7);self.assertEqual(entity.enchantments,[]);self.portable(g)

    def test_full_board_has_no_copy_allocation_or_late_stats(self):
        g=self.game(('copy',),board=('body',)*7);before=g.state.next_entity_id;self.play(g,'copy',self.target(g))
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.next_entity_id,before);self.portable(g)

    def test_dead_original_is_stale_and_does_not_create_a_fixed_copy(self):
        g=self.game(('dead-copy',));self.play(g,'dead-copy',self.target(g));self.assertEqual(g.state.players[1].board,[]);self.portable(g)

    def test_position_and_independent_attachment_ids_are_preserved(self):
        g=self.game(('prep','position'));source=self.target(g);self.play(g,'prep',source);self.play(g,'position',source)
        copied=self.copy(g);self.assertEqual(g.state.players[1].board[0],copied.id)
        self.assertFalse({e.id for e in copied.enchantments}&{e.id for e in g.state.entities[source].enchantments});self.portable(g)

    def test_original_attributed_copy_material_captures_fixed_stats(self):
        g=self.game(('prep','attributed'));source=self.target(g);self.play(g,'prep',source);self.play(g,'attributed',source)
        row=g.state.card_summon_history[-1];material=row.request.materials[0]
        self.assertEqual((material.profile,material.stats),('board_copy',FIXED))
        self.stats(self.copy(g),1,1);self.assertEqual(row.status,'completed');self.portable(g)

    def test_waiting_choice_restores_fixed_effect_and_failure_preserves_paid_boundary(self):
        g=self.game(('wait',));self.play(g,'wait',self.target(g));saved=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(restored);self.stats(self.copy(g),1,1);self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_attributed_copy_entry_wait_is_restorable_after_fixed_installation(self):
        g=self.game(('attributed',),board=('body','waiter'));self.play(g,'attributed',self.target(g))
        self.assertIsNotNone(g.state.pending_choice);self.stats(self.copy(g),1,1);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_immediate_failure_rolls_back_copy_allocation_and_stat_attachment(self):
        g=self.game(('fault',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.target(g))
        self.assertEqual(g.snapshot(),saved)

    def test_typed_frame_round_trip_and_player_information_boundaries(self):
        g=self.game();before=g.snapshot();effect=CopyMinion(self.target(g),1,stats=FIXED)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for player in (1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('CopyEntryMaterial','resolution_frame','card_summon_history','summon_stats'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
