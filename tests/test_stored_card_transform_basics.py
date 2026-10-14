"""General stored transformations reuse physical reset; held turn events already exist."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, HandProgressSpec, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TargetSpec, TransformStoredCard, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, ModifyCost,
    RequestChoice)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='a93552e30064ec8262e67b8eb09953ed60f8668eb601b078a91e278e315785c4'
CROC='CS2_120';KNIFE='CS2_082'


def evidence():
    p=json.loads((ROOT/'data/support/stored-card-transform-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Complete stored transformation evidence changed')
    return p


def registry():
    r=Registry('stored-card-transform-independent-v1')
    r.register_card(CardDefinition('st.hero','Diagnostic Mage',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    r.register_behavior('st.marker',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('st.spell','Diagnostic old spell',CardType.SPELL,cost=2,on_play='st.marker'))
    r.register_card(CardDefinition('st.newspell','Diagnostic new spell',CardType.SPELL,cost=4,on_play='st.marker'))
    r.register_card(CardDefinition('st.weapon','Diagnostic old weapon',CardType.WEAPON,cost=3,attack=3,durability=3))
    raw={x['id']:x for x in evidence()['records']}
    x=raw[CROC];r.register_card(CardDefinition(CROC,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],metadata=metadata_from_record(x)))
    x=raw[KNIFE];r.register_card(CardDefinition(KNIFE,x['name'],CardType.WEAPON,cost=x['cost'],attack=x['attack'],durability=x['health'],metadata=metadata_from_record(x)))
    r.register_card(CardDefinition('st.power','Diagnostic power',CardType.HERO_POWER,on_use='st.marker'))
    r.register_trigger_condition('st.own',lambda c:c.event.player_id==c.player_id)
    r.register_card(CardDefinition('st.watch','Diagnostic held listener',CardType.MINION,health=1,
        hand_progress=HandProgressSpec('event',on_complete='st.marker',repeat=True,event='turn_started',condition_id='st.own')))
    def card(c):return CardReference.capture(c.state.entities[c.target_id])
    def fail(c):raise ResolutionError('Diagnostic stored transformation failure')
    r.register_behavior('st.fail',fail)
    target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON))
    bodies={
        'discount':lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),),
        'buff':lambda c:(BuffStoredCard(card(c),5,7,c.source_id,cost=CostSpec(set_to=0)),),
        'to_s':lambda c:(TransformStoredCard(card(c),'st.newspell',c.source_id),),
        'to_w':lambda c:(TransformStoredCard(card(c),KNIFE,c.source_id),),
        'to_m':lambda c:(TransformStoredCard(card(c),CROC,c.source_id),),
        'same':lambda c:(TransformStoredCard(card(c),card(c).card_id,c.source_id),),
        'retained':lambda c:(TransformStoredCard(card(c),'st.newspell',c.source_id,retained_cost=1),),
        'stale':lambda c:(MoveCard(card(c),c.player_id,Zone.DECK,'top',source_id=c.source_id),
            TransformStoredCard(card(c),'st.newspell',c.source_id)),
        'bad':lambda c:(TransformStoredCard(card(c),'st.power',c.source_id),),
        'unknown_stale':lambda c:(MoveCard(card(c),c.player_id,Zone.DECK,'top',source_id=c.source_id),
            TransformStoredCard(card(c),'st.missing',c.source_id)),
        'fail_after':lambda c:(TransformStoredCard(card(c),'st.newspell',c.source_id),
            InvokeBehavior('st.fail',c.source_id,c.player_id)),
        'wait':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('transform','Transform',(TransformStoredCard(card(c),'st.newspell',c.source_id),)),
            ChoiceOption('fail','Fail',(TransformStoredCard(card(c),'st.newspell',c.source_id),
                InvokeBehavior('st.fail',c.source_id,c.player_id)))),c.source_id),),
    }
    for name,fn in bodies.items():
        r.register_behavior('st.'+name,fn)
        t=replace(target,kinds=(CardType.MINION,)) if name=='buff' else target
        r.register_card(CardDefinition('st.'+name,'Diagnostic '+name,CardType.SPELL,on_play='st.'+name,targeting=t))
    def deck(c):
        return (TransformStoredCard(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),
            'st.newspell',c.source_id),)
    r.register_behavior('st.deck',deck)
    r.register_card(CardDefinition('st.deck','Diagnostic fixed deck operation',CardType.SPELL,on_play='st.deck'))
    def return_held(c):
        i=next(i for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id=='st.watch')
        return (MoveCard(CardReference.capture(c.state.entities[i]),c.player_id,Zone.HAND,source_id=c.source_id),)
    r.register_behavior('st.return_held',return_held)
    def move_held(c):
        if c.event.player_id!=c.player_id or c.state.turn!=3:return ()
        i=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='st.watch')
        return (MoveCard(CardReference.capture(c.state.entities[i]),c.player_id,Zone.DECK,'top',source_id=c.source_id),
            InvokeBehavior('st.return_held',c.source_id,c.player_id))
    r.register_behavior('st.move_held',move_held)
    r.register_card(CardDefinition('st.observer','Diagnostic captured-lifecycle observer',CardType.MINION,health=2,
        triggers=(TriggerSpec('turn_started','st.move_held'),)))
    return r


class StoredCardTransformTests(unittest.TestCase):
    def game(self,hand=(),deck=(CROC,)*20,board=(),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('st.hero',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('st.hero',hand=enemy,deck=(CROC,)*20,max_mana=10,mana=10)),seed=61),registry())

    def card(self,g,name):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None):return g.apply(PlayCard(1,self.card(g,name),target))
    def cycle(self,g):
        g.apply(EndTurn(1));g.apply(EndTurn(2))
    def armor(self,g,player=1):return g.state.entities[g.state.players[player].hero_id].armor
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return s

    def test_full_raw_is_pinned_and_special_native_sources_remain_open(self):
        p=evidence();raw={x['id']:x for x in p['records']};self.assertEqual(len(raw),10)
        self.assertIn('original Cost',raw['DMF_108']['text_en']);self.assertIn('in your hand',raw['OG_123']['text_en'])
        self.assertIn('start of your turn',raw['WW_337t']['text_en'])
        for key in ('formal_pool_verified','CN_calibrated','full_shifter_sources_adapted',
                'full_mirage_adapted','full_shadow_adapted','full_deck_of_lunacy_adapted',
                'full_prestor_adapted','recurring_transform_source_retention_implemented'):
            self.assertFalse(p[key])
        self.assertTrue(set(('OG_123','UNG_929','LOOT_104','WW_337t','BOT_913','WC_017','DMF_108','SW_078')).isdisjoint(registry().cards))

    def test_effect_requires_physical_stored_reference_and_strict_numeric_retention(self):
        g=self.game(hand=('st.spell',),board=(CROC,));ref=CardReference.capture(g.state.entities[self.card(g,'st.spell')])
        for value in (True,-1,'1'):
            with self.assertRaises(ValueError):TransformStoredCard(ref,'st.newspell',retained_cost=value)
        with self.assertRaises(ValueError):TransformStoredCard(MinionReference.capture(g.state.entities[g.state.players[1].board[0]]),CROC)
        with self.assertRaises(ValueError):TransformStoredCard(ref,'')

    def test_spell_and_weapon_transform_clear_cost_and_keep_physical_hand_identity(self):
        for old,script,new in (('st.spell','st.to_s','st.newspell'),('st.weapon','st.to_w',KNIFE)):
            with self.subTest(kind=old):
                g=self.game(hand=(old,'st.discount',script));eid=self.card(g,old);before=g.state.entities[eid]
                self.play(g,'st.discount',eid);self.assertEqual(g.quote_cost(eid).amount,0)
                order=g.state.players[1].hand.index(eid);entries=len(g.state.hand_entries);rng=g.snapshot()['rng_state']
                self.play(g,script,eid);after=g.state.entities[eid]
                self.assertEqual((after.card_id,after.owner,after.controller,after.zone,after.hand_entry_id),
                    (new,before.owner,before.controller,Zone.HAND,before.hand_entry_id))
                self.assertEqual(after.zone_epoch,before.zone_epoch+1);self.assertEqual(after.enchantments,[])
                self.assertEqual(g.state.players[1].hand.index(eid),order);self.assertEqual(len(g.state.hand_entries),entries)
                self.assertEqual(g.quote_cost(eid).amount,g.registry.card(new).cost);self.assertEqual(g.snapshot()['rng_state'],rng)
                self.portable(g)

    def test_generic_minion_transform_uses_original_clear_attachment_lifecycle(self):
        g=self.game(hand=(CROC,'st.buff','st.to_m'));eid=self.card(g,CROC)
        self.play(g,'st.buff',eid);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(7,10))
        self.play(g,'st.to_m',eid);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health,g.quote_cost(eid).amount),(2,3,2));self.assertEqual(e.enchantments,[])
        self.portable(g)

    def test_explicit_retained_cost_installs_only_its_new_numeric_override(self):
        g=self.game(hand=('st.spell','st.discount','st.retained'));eid=self.card(g,'st.spell')
        self.play(g,'st.discount',eid);old={e.id for e in g.state.entities[eid].enchantments}
        self.play(g,'st.retained',eid);e=g.state.entities[eid]
        self.assertEqual(e.card_id,'st.newspell');self.assertEqual(g.quote_cost(eid).amount,1)
        self.assertEqual(len(e.enchantments),1);self.assertTrue(old.isdisjoint({x.id for x in e.enchantments}));self.portable(g)

    def test_deck_spell_transform_keeps_slot_owner_and_no_hand_acquisition(self):
        g=self.game(hand=('st.deck',),deck=('st.spell',CROC));eid=g.state.players[1].deck[0];before=g.state.entities[eid]
        slots=g.state.players[1].deck;entries=g.state.hand_entries
        self.play(g,'st.deck');e=g.state.entities[eid]
        self.assertEqual(g.state.players[1].deck,slots);self.assertEqual(g.state.hand_entries,entries)
        self.assertEqual((e.card_id,e.owner,e.controller,e.zone,e.zone_epoch),('st.newspell',before.owner,before.controller,Zone.DECK,before.zone_epoch+1))
        self.portable(g)

    def test_cross_type_stored_face_change_does_not_play_or_summon_the_destination(self):
        g=self.game(hand=('st.spell','st.to_m'));eid=self.card(g,'st.spell');self.play(g,'st.to_m',eid)
        self.assertEqual(g.state.entities[eid].kind,CardType.MINION);self.assertEqual(g.state.players[1].board,[])
        self.assertFalse(any(e.kind=='minion_summoned' for e in g.events))
        self.assertEqual(len(g.state.play_history),1);self.play(g,CROC)
        self.assertIn(eid,g.state.players[1].board);self.portable(g)

    def test_same_face_transform_resets_printed_listener_and_its_old_instance(self):
        g=self.game(hand=('st.watch','st.same'));eid=self.card(g,'st.watch');self.cycle(g)
        old=progress_ability(g.state.entities[eid]);self.assertEqual(old.progress_completions,1)
        epoch=g.state.entities[eid].zone_epoch;self.play(g,'st.same',eid);new=progress_ability(g.state.entities[eid])
        self.assertNotEqual(new.id,old.id);self.assertEqual((new.progress_completions,new.progress_keys),(0,()))
        self.assertEqual(g.state.entities[eid].zone_epoch,epoch+1);self.cycle(g)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions,1);self.assertEqual(self.armor(g),2)
        self.portable(g)

    def test_departed_captured_card_is_skipped_without_transforming_its_new_zone(self):
        g=self.game(hand=('st.spell','st.stale'));eid=self.card(g,'st.spell');self.play(g,'st.stale',eid)
        self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].zone),('st.spell',Zone.DECK))
        self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.portable(g)

    def test_nonphysical_destination_rejects_and_rolls_back_the_accepted_root(self):
        g=self.game(hand=('st.spell','st.bad'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'physical hand/deck'):self.play(g,'st.bad',self.card(g,'st.spell'))
        self.assertEqual(g.snapshot(),s)

    def test_unknown_destination_is_not_silently_ignored_for_a_stale_reference(self):
        g=self.game(hand=('st.spell','st.unknown_stale'));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'st.unknown_stale',self.card(g,'st.spell'))
        self.assertEqual(g.snapshot(),s)

    def test_opcode_waiting_restores_clones_and_replays_with_independent_registry(self):
        g=self.game(hand=('st.spell','st.wait'));eid=self.card(g,'st.spell');self.play(g,'st.wait',eid);s=self.portable(g)
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('transform',)))
        restored=Game.from_snapshot(s,registry());restored.apply(SelectChoice(1,choice.id,('transform',)))
        self.assertEqual(restored.snapshot(),g.snapshot());self.assertEqual(g.state.entities[eid].card_id,'st.newspell');self.portable(g)

    def test_failure_after_transform_rolls_back_face_epoch_knowledge_and_receipts(self):
        g=self.game(hand=('st.spell','st.fail_after'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic stored transformation failure'):
            self.play(g,'st.fail_after',self.card(g,'st.spell'))
        self.assertEqual(g.snapshot(),s)
        g=self.game(hand=('st.spell','st.wait'));self.play(g,'st.wait',self.card(g,'st.spell'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic stored transformation failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)

    def test_hidden_original_type_does_not_leak_through_general_transform(self):
        games=[self.game(hand=(name,'st.to_s')) for name in ('st.spell','st.weapon')]
        for g,name in zip(games,('st.spell','st.weapon')):self.play(g,'st.to_s',self.card(g,name))
        self.assertEqual(games[0].for_player(2).observe(),games[1].for_player(2).observe())
        self.assertEqual(games[0].for_player(2).events(),games[1].for_player(2).events())
        own=games[0].for_player(1).observe()['observation']['players'][0]['hand'][0]
        self.assertEqual(own['card_id'],'st.newspell')

    def test_existing_repeated_hand_turn_listener_uses_each_controllers_start_only(self):
        g=self.game(hand=('st.watch',),enemy=('st.watch',));eid=self.card(g,'st.watch')
        self.cycle(g);self.assertEqual((self.armor(g),self.armor(g,2)),(1,1))
        self.cycle(g);self.assertEqual((self.armor(g),self.armor(g,2)),(2,2))
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions,2);self.portable(g)

    def test_card_drawn_after_start_is_not_added_to_the_old_held_window(self):
        g=self.game(hand=('st.watch',),deck=('st.watch',CROC,CROC,CROC));first=self.card(g,'st.watch')
        self.cycle(g);second=next(i for i in g.state.players[1].hand if i!=first and g.state.entities[i].card_id=='st.watch')
        self.assertEqual((progress_ability(g.state.entities[first]).progress_completions,
            progress_ability(g.state.entities[second]).progress_completions),(1,0))
        self.cycle(g);self.assertEqual((progress_ability(g.state.entities[first]).progress_completions,
            progress_ability(g.state.entities[second]).progress_completions),(2,1));self.assertEqual(self.armor(g),3)
        self.portable(g)

    def test_departure_and_return_do_not_reanimate_the_captured_hand_listener(self):
        g=self.game(hand=('st.watch',),board=('st.observer',));eid=self.card(g,'st.watch');self.cycle(g)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.assertEqual(self.armor(g),0)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_completions,0)
        self.cycle(g);self.assertEqual(self.armor(g),1);self.portable(g)

    def test_new_opcode_codec_rejects_unknown_fields_and_boolean_cost(self):
        g=self.game(hand=('st.spell','st.wait'));self.play(g,'st.wait',self.card(g,'st.spell'))
        effect=g._frame.options[0].effects[0];codec=FrameCodec(g.mechanics,g.registry);encoded=codec.encode(effect)
        self.assertEqual(codec.decode(encoded),effect)
        bad=json.loads(json.dumps(encoded));bad['fields']['unknown']=True
        with self.assertRaises(ValueError):codec.decode(bad)
        bad=json.loads(json.dumps(encoded));bad['fields']['retained_cost']=True
        with self.assertRaises(ValueError):codec.decode(bad)
        s=g.snapshot();wrong=json.loads(json.dumps(s));wrong['ruleset']['id']='prototype-v262'
        with self.assertRaises(SnapshotError):Game.from_snapshot(wrong,registry())


if __name__=='__main__':unittest.main()
