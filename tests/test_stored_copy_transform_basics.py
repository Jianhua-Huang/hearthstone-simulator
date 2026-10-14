"""Current physical copy into an existing recipient reuses the stored-copy recipe."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

import test_stored_card_transform_basics as base
from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, TransformStoredIntoCopy, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='0ecc30a19086b781ce5d75556cf01a4d6f8ebb026fa8a9415cc8afc515304123'


def evidence():
    p=json.loads((ROOT/'data/support/stored-copy-transform-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Stored current-copy evidence changed')
    return p


def registry():
    r=base.registry()
    def refs(c):
        target=CardReference.capture(c.state.entities[c.target_id])
        i=next(i for i in c.state.players[2].hand if c.state.entities[i].card_id!='sc.filler')
        return target,CardReference.capture(c.state.entities[i])
    def operation(c):return TransformStoredIntoCopy(*refs(c),c.source_id)
    def fail(c):raise ResolutionError('Diagnostic current-copy failure')
    r.register_behavior('sc.fail',fail)
    bodies={
        'copy':lambda c:(operation(c),),
        'self':lambda c:(TransformStoredIntoCopy(*(CardReference.capture(c.state.entities[c.target_id]),)*2,c.source_id),),
        'alter':lambda c:(ModifyCost(refs(c)[1].entity_id,CostSpec(set_to=1),c.source_id),operation(c)),
        'source_stale':lambda c:(MoveCard(refs(c)[1],2,Zone.DECK,'top',source_id=c.source_id),operation(c)),
        'target_stale':lambda c:(MoveCard(refs(c)[0],1,Zone.DECK,'top',source_id=c.source_id),operation(c)),
        'fail_after':lambda c:(operation(c),InvokeBehavior('sc.fail',c.source_id,c.player_id)),
        'wait':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('copy','Copy',(operation(c),)),
            ChoiceOption('fail','Fail',(operation(c),InvokeBehavior('sc.fail',c.source_id,c.player_id)))),c.source_id),),
        'modify_source':lambda c:(ModifyCost(refs(c)[1].entity_id,CostSpec(set_to=0),c.source_id),),
        'buff_source':lambda c:(BuffStoredCard(refs(c)[1],4,5,c.source_id,cost=CostSpec(set_to=0)),),
        'newcopy':lambda c:(CopyCard(refs(c)[1],1,source_id=c.source_id),),
    }
    for name,fn in bodies.items():
        r.register_behavior('sc.'+name,fn)
        r.register_card(CardDefinition('sc.'+name,'Diagnostic '+name,CardType.SPELL,on_play='sc.'+name,
            targeting=r.card('st.to_s').targeting))
    def deck_source(c):
        return (TransformStoredIntoCopy(CardReference.capture(c.state.entities[c.target_id]),
            CardReference.capture(c.state.entities[c.state.players[2].deck[0]]),c.source_id),)
    r.register_behavior('sc.deck_source',deck_source)
    r.register_card(CardDefinition('sc.deck_source','Diagnostic fixed deck source',CardType.SPELL,
        on_play='sc.deck_source',targeting=r.card('st.to_s').targeting))
    return r


class StoredCopyTransformTests(unittest.TestCase):
    def game(self,hand=(),enemy=(base.CROC,),enemy_deck=(base.CROC,)*15):
        return Game.from_scenario(Scenario((
            PlayerSetup('st.hero',hand=hand,deck=(base.CROC,)*15,max_mana=10,mana=10),
            PlayerSetup('st.hero',hand=enemy,deck=enemy_deck,max_mana=10,mana=10)),seed=89),registry())
    def card(self,g,name):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target):return g.apply(PlayCard(1,self.card(g,name),target))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return s

    def test_real_sources_are_pinned_without_claiming_complete_special_lifecycles(self):
        p=evidence();self.assertEqual(len(p['records']),8)
        for key in ('full_chameleos_adapted','full_mirage_adapted','full_shadow_adapted',
                'defining_source_lifecycle_verified','formal_pool_verified','CN_calibrated','composite_copy_supported'):
            self.assertFalse(p[key])
        self.assertTrue(set(('GIL_142','WW_337t','RLK_567')).isdisjoint(registry().cards))

    def test_minion_material_replaces_recipient_but_preserves_its_physical_identity(self):
        g=self.game(hand=('st.spell','sc.buff_source','sc.copy'));eid=self.card(g,'st.spell');source=g.state.players[2].hand[0]
        self.play(g,'sc.buff_source',eid);source_before=g.state.entities[source];target_before=g.state.entities[eid]
        count=g.state.next_entity_id;entries=g.state.hand_entries;self.play(g,'sc.copy',eid);e=g.state.entities[eid]
        self.assertEqual((e.card_id,e.kind,e.owner,e.controller,e.zone,e.hand_entry_id),
            (base.CROC,CardType.MINION,1,1,Zone.HAND,target_before.hand_entry_id))
        self.assertEqual((e.attack,e.health,g.quote_cost(eid).amount),(6,8,0))
        self.assertEqual(e.zone_epoch,target_before.zone_epoch+1);self.assertEqual(g.state.next_entity_id,count)
        self.assertEqual(g.state.hand_entries,entries);self.assertEqual(g.state.entities[source],source_before)
        self.assertTrue({x.id for x in e.enchantments}.isdisjoint({x.id for x in source_before.enchantments}));self.portable(g)

    def test_spell_and_weapon_current_modifications_are_copied_without_source_control(self):
        for name,kind in (('st.spell',CardType.SPELL),('st.weapon',CardType.WEAPON)):
            g=self.game(hand=(base.CROC,'sc.modify_source','sc.copy'),enemy=(name,));eid=self.card(g,base.CROC)
            self.play(g,'sc.modify_source',eid);self.play(g,'sc.copy',eid);e=g.state.entities[eid]
            self.assertEqual((e.card_id,e.kind,e.owner,e.controller),(name,kind,1,1));self.assertEqual(g.quote_cost(eid).amount,0)
            self.assertEqual(e.durability,g.state.entities[g.state.players[2].hand[0]].durability);self.portable(g)

    def test_recipient_old_modifications_are_replaced_instead_of_accumulated(self):
        g=self.game(hand=(base.CROC,'st.buff','sc.copy'));eid=self.card(g,base.CROC)
        self.play(g,'st.buff',eid);old={x.id for x in g.state.entities[eid].enchantments};self.play(g,'sc.copy',eid)
        e=g.state.entities[eid];self.assertEqual((e.attack,e.health,g.quote_cost(eid).amount),(2,3,2))
        self.assertTrue(old.isdisjoint({x.id for x in e.enchantments}));self.assertEqual(e.enchantments,[]);self.portable(g)

    def test_matching_source_is_read_at_execution_after_earlier_modification(self):
        g=self.game(hand=('st.spell','sc.alter'),enemy=('st.newspell',));eid=self.card(g,'st.spell')
        self.play(g,'sc.alter',eid);self.assertEqual(g.quote_cost(eid).amount,1)
        self.assertEqual(g.state.entities[eid].card_id,'st.newspell');self.portable(g)

    def test_self_copy_captures_material_before_resetting_the_same_entity(self):
        g=self.game(hand=(base.CROC,'st.buff','sc.self'));eid=self.card(g,base.CROC);self.play(g,'st.buff',eid)
        before=g.state.entities[eid];self.play(g,'sc.self',eid);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health,g.quote_cost(eid).amount),(7,10,0));self.assertEqual(e.zone_epoch,before.zone_epoch+1)
        self.assertTrue({x.id for x in e.enchantments}.isdisjoint({x.id for x in before.enchantments}));self.portable(g)

    def test_departed_source_or_recipient_does_not_materialize_an_old_reference(self):
        for script,zone in (('sc.source_stale',Zone.HAND),('sc.target_stale',Zone.DECK)):
            g=self.game(hand=('st.spell',script));eid=self.card(g,'st.spell');self.play(g,script,eid)
            self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].zone),('st.spell',zone))
            self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.portable(g)

    def test_physical_deck_source_is_not_drawn_moved_or_disclosed(self):
        g=self.game(hand=('st.spell','sc.deck_source'),enemy_deck=('st.weapon',base.CROC));eid=self.card(g,'st.spell')
        source=g.state.entities[g.state.players[2].deck[0]];deck=g.state.players[2].deck
        self.play(g,'sc.deck_source',eid);self.assertEqual(g.state.entities[eid].card_id,'st.weapon')
        self.assertEqual(g.state.players[2].deck,deck);self.assertEqual(g.state.entities[source.id],source)
        self.assertFalse(any(e.kind in ('card_created','card_drawn','card_added_to_hand') for e in g.events));self.portable(g)

    def test_pending_opcode_restores_and_replays_with_independent_registry(self):
        g=self.game(hand=('st.spell','sc.wait'));eid=self.card(g,'st.spell');self.play(g,'sc.wait',eid);s=self.portable(g)
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('copy',)))
        other=Game.from_snapshot(s,registry());other.apply(SelectChoice(1,choice.id,('copy',)))
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(g.state.entities[eid].card_id,base.CROC);self.portable(g)

    def test_failed_direct_or_choice_copy_rolls_back_material_identity_and_knowledge(self):
        g=self.game(hand=('st.spell','sc.fail_after'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic current-copy failure'):
            self.play(g,'sc.fail_after',self.card(g,'st.spell'))
        self.assertEqual(g.snapshot(),s)
        g=self.game(hand=('st.spell','sc.wait'));self.play(g,'sc.wait',self.card(g,'st.spell'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic current-copy failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)

    def test_private_recipient_original_does_not_leak_through_copy(self):
        games=[self.game(hand=(name,'sc.copy')) for name in ('st.spell','st.weapon')]
        for g,name in zip(games,('st.spell','st.weapon')):self.play(g,'sc.copy',self.card(g,name))
        self.assertEqual(games[0].for_player(2).observe(),games[1].for_player(2).observe())
        self.assertEqual(games[0].for_player(2).events(),games[1].for_player(2).events())

    def test_references_and_opcode_fields_are_strict(self):
        g=self.game(hand=('st.spell','sc.wait'));eid=self.card(g,'st.spell');ref=CardReference.capture(g.state.entities[eid])
        with self.assertRaises(ValueError):TransformStoredIntoCopy(ref,replace(ref,zone=Zone.BOARD))
        self.play(g,'sc.wait',eid);codec=FrameCodec(g.mechanics,g.registry);effect=g._frame.options[0].effects[0]
        encoded=codec.encode(effect);self.assertEqual(codec.decode(encoded),effect)
        encoded['fields']['preserve_everything']=True
        with self.assertRaises(ValueError):codec.decode(encoded)


if __name__=='__main__':unittest.main()
