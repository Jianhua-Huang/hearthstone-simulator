"""Terminal printed derivatives and R-085 provisional generation windows."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BuffStoredCard, CardDefinition, CardType, CostSpec,
    CreateTemporaryCard, EndTurn, Game, HandDerivativeSpec, HandRepeatSpec, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, ShatterSpec,
    SnapshotError, SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption, Damage,
    Destroy, Draw, GainArmor, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.hand_derivatives import CreatePlayDerivative
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard


class HandDerivativeTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.spell('plain', lambda c: [])
        self.spell('twin_child', lambda c: [GainArmor(c.player_id, 1)], cost=2)
        self.spell('twin', lambda c: [GainArmor(c.player_id, 1)], cost=2,
            keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL, 'twin_child'),))
        self.r.register_card(CardDefinition('mini', 'mini', CardType.MINION,
            cost=1, attack=1, health=1, keywords=(Keyword.MINI,)))
        self.r.register_card(CardDefinition('giant', 'giant', CardType.MINION,
            cost=8, attack=8, health=8, keywords=(Keyword.GIGANTIC,)))
        self.root('small_root', Keyword.MINIATURIZE, 'mini')
        self.root('large_root', Keyword.GIGANTIFY, 'giant')

    def root(self, name, keyword, child, **kw):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, cost=2,
            attack=2, health=3, keywords=(keyword,),
            hand_derivatives=(HandDerivativeSpec(keyword, child),), **kw))

    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, hand=(), board=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, deck=('plain',)*12, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=('plain',)*12, max_mana=10, mana=10)), seed=192), self.r)

    def cards(self, g):
        s = g.state
        return [s.entities[i] for i in s.players[1].hand]
    def find(self, g, name): return next(e.id for e in self.cards(g) if e.card_id == name)
    def play(self, g, name, **kw):
        eid = self.find(g, name); g.apply(PlayCard(1, eid, **kw)); return eid
    def ref(self, c, name):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand
                                         if c.state.entities[i].card_id == name))
    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor
    def check(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap, self.r).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snap)
    def twin(self, name, fn, **kw):
        self.spell(name, fn, cost=2, keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL, 'twin_child'),), **kw)
    def watcher(self, fn, event='card_played'):
        self.r.register_behavior('watch', fn)
        self.r.register_card(CardDefinition('watch', 'watch', CardType.MINION, health=2,
            triggers=(TriggerSpec(event, 'watch'),)))

    def test_twin_is_new_terminal_entity_with_same_effect(self):
        g=self.game(('twin',)); original=self.play(g,'twin'); child=self.cards(g)[0]
        self.assertNotEqual(original,child.id); self.assertEqual(child.origin_entity_id,original)
        self.assertNotIn(Keyword.TWINSPELL,child.keywords); self.assertIsNone(child.hand_lifetime)
        self.play(g,'twin_child'); self.assertFalse(self.cards(g))
        self.assertEqual((g.state.players[1].mana,self.armor(g)),(6,2)); self.check(g)

    def test_terminal_base_copy_does_not_regain_keyword(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'twin_child'),1,mode='base')])
        g=self.game(('twin','copy')); self.play(g,'twin'); self.play(g,'copy')
        self.play(g,'twin_child'); self.play(g,'twin_child')
        self.assertFalse(self.cards(g)); self.assertEqual(self.armor(g),3); self.check(g)

    def test_discount_on_root_not_inherited(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'twin').entity_id,CostSpec(set_to=0))])
        g=self.game(('discount','twin')); self.play(g,'discount'); self.play(g,'twin')
        self.assertEqual(g.quote_cost(self.find(g,'twin_child')).amount,2); self.check(g)

    def test_global_discount_applies_to_terminal_form(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-5))])
        g=self.game(('discount','small_root')); self.play(g,'discount'); self.play(g,'small_root')
        self.assertEqual(g.quote_cost(self.find(g,'mini')).amount,0); self.check(g)

    def test_twin_generation_after_payload_can_burn(self):
        self.twin('draw_twin',lambda c:[Draw(1)])
        g=self.game(('draw_twin',)+('plain',)*9); self.play(g,'draw_twin')
        self.assertEqual(len(self.cards(g)),10)
        burned=[e for e in g.events if e.kind=='card_burned']
        self.assertEqual(len(burned),1)
        self.assertEqual(g.state.entities[burned[0].target_id].card_id,'twin_child'); self.check(g)

    def test_countered_spell_has_no_twin_derivative(self):
        g=self.game(('twin',),enemy_hand=('EX1_287',)); g.apply(EndTurn(1))
        g.apply(PlayCard(2,next(i for i in g.state.players[2].hand if g.state.entities[i].card_id=='EX1_287')))
        g.apply(EndTurn(2)); self.play(g,'twin')
        self.assertFalse(any(e.card_id=='twin_child' for e in self.cards(g)))
        self.assertEqual(self.armor(g),0); self.assertTrue(g.state.play_history[-1].countered); self.check(g)

    def test_repeat_payload_creates_one_twin_per_iteration(self):
        self.r.register_card(CardDefinition('repeater','repeater',CardType.MINION,health=2,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(('twin',),board=('repeater',)); self.play(g,'twin')
        self.assertEqual([e.card_id for e in self.cards(g)],['twin_child']*2)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(2,8)); self.check(g)

    def test_twin_choice_restores_before_generation_without_duplicates(self):
        self.twin('choose',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',(GainArmor(1,3),)),),c.source_id)])
        g=self.game(('choose',)); self.play(g,'choose'); self.assertFalse(self.cards(g)); self.check(g)
        pending=g.state.pending_choice; g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,pending.id,('yes',)))
        self.assertEqual([e.card_id for e in self.cards(g)],['twin_child'])
        self.assertEqual(self.armor(g),3); self.check(g)

    def test_failure_after_effects_rolls_back_entire_action(self):
        self.r.register_behavior('bad',lambda c:[GainArmor(1,-1)])
        self.twin('fail',lambda c:[GainArmor(1,2),InvokeBehavior('bad',c.source_id,1)])
        g=self.game(('fail',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_lethal_payload_stops_pending_derivative(self):
        self.twin('lethal',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id)])
        g=self.game(('lethal',)); self.play(g,'lethal')
        self.assertEqual(g.state.winner,1); self.assertFalse(self.cards(g)); self.check(g)

    def test_mini_and_giant_have_independent_printed_size(self):
        for root,child,size in (('small_root','mini',1),('large_root','giant',8)):
            with self.subTest(root=root):
                g=self.game((root,)); source=self.play(g,root); e=self.cards(g)[0]
                self.assertEqual((e.card_id,e.cost,e.attack,e.health),(child,size,size,size))
                self.assertEqual(e.origin_entity_id,source); self.check(g)

    def test_mini_terminal_play_does_not_generate_again(self):
        g=self.game(('small_root',)); self.play(g,'small_root'); self.play(g,'mini')
        self.assertFalse(self.cards(g)); self.assertEqual(len(g.state.players[1].board),2); self.check(g)

    def test_giant_terminal_play_does_not_generate_again(self):
        g=self.game(('large_root',)); self.play(g,'large_root'); self.play(g,'giant')
        self.assertFalse(self.cards(g)); self.assertEqual(g.state.players[1].mana,0); self.check(g)

    def test_parent_hand_buffs_do_not_change_derivative(self):
        self.spell('buff',lambda c:[BuffStoredCard(self.ref(c,'small_root'),4,5)])
        g=self.game(('buff','small_root')); self.play(g,'buff'); root=self.play(g,'small_root')
        self.assertEqual(g.state.entities[root].attack,6)
        self.assertEqual((self.cards(g)[0].attack,self.cards(g)[0].health),(1,1)); self.check(g)

    def test_dual_keywords_keep_declared_order_and_capacity(self):
        self.r.register_card(CardDefinition('dual','dual',CardType.MINION,health=3,
            keywords=(Keyword.MINIATURIZE,Keyword.GIGANTIFY),hand_derivatives=(
                HandDerivativeSpec(Keyword.MINIATURIZE,'mini'),HandDerivativeSpec(Keyword.GIGANTIFY,'giant'))))
        g=self.game(('dual',)+('plain',)*9); self.play(g,'dual')
        self.assertEqual(self.cards(g)[-1].card_id,'mini')
        burned=next(e for e in g.events if e.kind=='card_burned')
        self.assertEqual(g.state.entities[burned.target_id].card_id,'giant'); self.check(g)

    def test_direct_summon_does_not_generate(self):
        self.spell('summon',lambda c:[Summon(1,'small_root'),Summon(1,'large_root')])
        g=self.game(('summon',)); self.play(g,'summon')
        self.assertFalse(self.cards(g)); self.assertEqual(len(g.state.players[1].board),2); self.check(g)

    def test_source_transform_does_not_change_captured_identity(self):
        self.r.register_behavior('transform',lambda c:[Transform(c.source_id,'CS2_182')])
        self.root('changing',Keyword.MINIATURIZE,'mini',on_play='transform')
        g=self.game(('changing',)); source=self.play(g,'changing')
        self.assertEqual(g.state.entities[source].card_id,'CS2_182')
        self.assertEqual(self.cards(g)[0].card_id,'mini'); self.check(g)

    def test_source_self_silence_does_not_remove_captured_generation(self):
        self.r.register_behavior('silence',lambda c:[Silence(c.source_id)])
        self.root('silent',Keyword.MINIATURIZE,'mini',on_play='silence')
        g=self.game(('silent',)); self.play(g,'silent')
        self.assertEqual(self.cards(g)[0].card_id,'mini'); self.check(g)

    def test_source_death_does_not_remove_captured_generation(self):
        self.r.register_behavior('die',lambda c:[Destroy(c.source_id)])
        self.root('dying',Keyword.GIGANTIFY,'giant',on_play='die')
        g=self.game(('dying',)); source=self.play(g,'dying')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.cards(g)[0].origin_entity_id,source); self.check(g)

    def test_source_bounce_retains_original_and_generates_terminal_form(self):
        self.r.register_behavior('bounce',lambda c:[ReturnToHand(c.source_id)])
        self.root('bouncing',Keyword.MINIATURIZE,'mini',on_play='bounce')
        g=self.game(('bouncing',)); source=self.play(g,'bouncing')
        self.assertEqual([e.card_id for e in self.cards(g)],['bouncing','mini'])
        self.assertEqual(self.find(g,'bouncing'),source); self.check(g)

    def test_after_play_reaction_capacity_precedes_mini_generation(self):
        self.watcher(lambda c:[AddToHand(1,'plain')])
        g=self.game(('small_root',)+('plain',)*9,board=('watch',)); self.play(g,'small_root')
        self.assertFalse(any(e.card_id=='mini' for e in self.cards(g)))
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1); self.check(g)

    def test_after_play_choice_can_restore_queued_mini(self):
        self.watcher(lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)])
        g=self.game(('small_root',),board=('watch',)); self.play(g,'small_root')
        self.assertFalse(self.cards(g)); self.check(g)
        pending=g.state.pending_choice; g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,pending.id,('yes',)))
        self.assertEqual([e.card_id for e in self.cards(g)],['mini']); self.check(g)

    def test_magnetic_generates_form_without_transferring_entry_keyword(self):
        self.r.register_card(CardDefinition('mag','mag',CardType.MINION,cost=2,attack=2,health=3,
            keywords=(Keyword.MAGNETIC,Keyword.MINIATURIZE),magnetic_tribes=('mech',),
            hand_derivatives=(HandDerivativeSpec(Keyword.MINIATURIZE,'mini'),)))
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,attack=2,health=3,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))))
        g=self.game(('mag',),board=('mech',)); source=self.play(g,'mag',position=0)
        host=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual(host.attack,4); self.assertNotIn(Keyword.MINIATURIZE,host.keywords)
        self.assertEqual(self.cards(g)[0].origin_entity_id,source); self.check(g)

    def test_temporary_parent_produces_permanent_derivative(self):
        self.spell('get',lambda c:[CreateTemporaryCard(1,'small_root',c.state.turn,source_id=c.source_id)])
        g=self.game(('get',)); self.play(g,'get'); self.play(g,'small_root'); g.apply(EndTurn(1))
        self.assertEqual([e.card_id for e in self.cards(g)],['mini'])
        self.assertIsNone(self.cards(g)[0].hand_lifetime); self.check(g)

    def test_echo_twin_composes_one_temporary_root_and_permanent_child(self):
        self.spell('echo_twin',lambda c:[],cost=2,keywords=(Keyword.ECHO,Keyword.TWINSPELL),
            hand_repeat=HandRepeatSpec(),hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'twin_child'),))
        g=self.game(('echo_twin',)); self.play(g,'echo_twin')
        self.assertEqual([e.card_id for e in self.cards(g)],['echo_twin','twin_child'])
        self.assertIsNotNone(self.cards(g)[0].hand_lifetime); self.assertIsNone(self.cards(g)[1].hand_lifetime)
        g.apply(EndTurn(1)); self.assertEqual([e.card_id for e in self.cards(g)],['twin_child']); self.check(g)

    def test_twin_derivative_can_enter_shatter_pipeline(self):
        self.r.register_card(CardDefinition('split','split',CardType.SPELL,cost=2,
            keywords=(Keyword.SHATTER,),shatter=ShatterSpec('L','R')))
        for name in ('L','R'):
            self.r.register_card(CardDefinition(name,name,CardType.SPELL,keywords=(Keyword.SHATTERED,)))
        self.spell('split_twin',lambda c:[],cost=2,keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'split'),))
        g=self.game(('split_twin','plain')); self.play(g,'split_twin')
        self.assertEqual(sorted(e.card_id for e in self.cards(g)),['L','R','plain']); self.check(g)

    def test_player_port_uses_same_derivation_and_hides_opponent_hand(self):
        g=self.game(('small_root',)); port=g.for_player(1); listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(self.cards(g)[0].card_id,'mini')
        self.assertNotIn('"mini"',json.dumps(g.observe(2)['players'][0]['hand']))
        self.assertNotIn('"mini"',json.dumps(g.player_events(2))); self.check(g)

    def test_corrupt_captured_form_rejected(self):
        g=self.game(('small_root',)); self.play(g,'small_root')
        for key,value in (('keyword','unknown'),('keyword','twinspell'),('card_id','giant'),('card_id','unknown')):
            snap=g.snapshot(); snap['state']['play_history'][0]['hand_derivatives'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(SnapshotError): Game.from_snapshot(snap,self.r)

    def test_missing_captured_field_rejected(self):
        g=self.game(('small_root',)); self.play(g,'small_root'); snap=g.snapshot()
        del snap['state']['play_history'][0]['hand_derivatives']
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap,self.r)

    def test_bare_grant_of_generation_or_form_marker_is_rejected(self):
        for keyword in (Keyword.TWINSPELL,Keyword.MINIATURIZE,Keyword.GIGANTIFY,Keyword.MINI,Keyword.GIGANTIC):
            self.spell('grant_'+keyword.value,lambda c,k=keyword:[GrantKeyword(c.state.players[1].board[0],k)])
        g=self.game(tuple('grant_'+k.value for k in (Keyword.TWINSPELL,Keyword.MINIATURIZE,Keyword.GIGANTIFY,Keyword.MINI,Keyword.GIGANTIC)),board=('mini',))
        for name in [e.card_id for e in self.cards(g)]:
            before=g.snapshot()
            with self.subTest(name=name),self.assertRaises(ResolutionError): self.play(g,name)
            self.assertEqual(g.snapshot(),before)

    def test_source_control_change_keeps_derivative_for_original_player(self):
        self.r.register_behavior('give',lambda c:[ChangeControl(c.source_id,2)])
        self.root('giving',Keyword.MINIATURIZE,'mini',on_play='give')
        g=self.game(('giving',)); source=self.play(g,'giving')
        self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual(self.cards(g)[0].controller,1); self.check(g)

    def test_twin_repeated_choice_restores_between_iterations(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=2,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.twin('choose_repeat',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',(GainArmor(1,2),)),),c.source_id)])
        g=self.game(('choose_repeat',),board=('repeat',)); self.play(g,'choose_repeat'); self.check(g)
        pending=g.state.pending_choice; g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,pending.id,('yes',)))
        while g.state.pending_choice:
            self.check(g); pending=g.state.pending_choice; g=Game.from_snapshot(g.snapshot(),self.r)
            g.apply(SelectChoice(1,pending.id,('yes',)))
        self.assertEqual(len(self.cards(g)),2); self.assertEqual(self.armor(g),4); self.check(g)

    def test_choice_after_derivative_restores_without_creating_twice(self):
        self.watcher(lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)],'card_added_to_hand')
        g=self.game(('twin',),board=('watch',)); self.play(g,'twin')
        self.assertEqual(len(self.cards(g)),1); self.check(g)
        pending=g.state.pending_choice; g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,pending.id,('yes',)))
        self.assertEqual(len(self.cards(g)),1); self.check(g)

    def test_derivative_trigger_failure_rolls_back_generated_entity(self):
        self.watcher(lambda c:[GainArmor(1,-1)],'card_added_to_hand')
        g=self.game(('twin',),board=('watch',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'twin')
        self.assertEqual(g.snapshot(),before)

    def test_forged_creation_in_wrong_phase_is_rejected(self):
        self.spell('forge',lambda c:[CreatePlayDerivative(1,HandDerivativeSpec(Keyword.TWINSPELL,'twin_child'))])
        g=self.game(('twin','forge')); self.play(g,'twin'); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'forge')
        self.assertEqual(g.snapshot(),before)


class HandDerivativeDefinitionTests(unittest.TestCase):
    def definitions(self, **changes):
        child=CardDefinition('child','child',CardType.SPELL,cost=2)
        root=CardDefinition('root','root',CardType.SPELL,cost=2,keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'child'),))
        return replace(root,**changes),child
    def reject(self,*cards):
        with self.assertRaises((ValueError,KeyError)):
            r=build_registry()
            for card in cards:r.register_card(card)
            r.freeze()
    def test_keyword_requires_declaration(self):
        self.reject(*self.definitions(hand_derivatives=()))
    def test_declaration_requires_keyword(self):
        self.reject(*self.definitions(keywords=()))
    def test_derivative_cannot_be_self_or_unknown(self):
        for child in ('root','missing'):
            self.reject(*self.definitions(hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,child),)))
    def test_derivative_cannot_recurse(self):
        root,child=self.definitions()
        self.reject(root,replace(child,keywords=(Keyword.TWINSPELL,),hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'root'),)))
    def test_derivative_must_match_kind_and_printed_cost(self):
        root,child=self.definitions()
        self.reject(root,replace(child,cost=1)); self.reject(root,replace(child,kind=CardType.MINION,health=1))
    def test_mini_form_requires_marker_and_size(self):
        root=CardDefinition('root','root',CardType.MINION,health=2,keywords=(Keyword.MINIATURIZE,),
            hand_derivatives=(HandDerivativeSpec(Keyword.MINIATURIZE,'child'),))
        child=CardDefinition('child','child',CardType.MINION,cost=1,attack=1,health=1,keywords=(Keyword.MINI,))
        for bad in (replace(child,cost=2),replace(child,attack=2),replace(child,health=2),replace(child,keywords=())):
            self.reject(root,bad)
    def test_declarations_are_unique_and_immutable(self):
        root,child=self.definitions()
        self.reject(replace(root,hand_derivatives=root.hand_derivatives*2),child)
        self.reject(replace(root,hand_derivatives=list(root.hand_derivatives)),child)
    def test_form_marker_cannot_mark_a_spell(self):
        self.reject(CardDefinition('bad','bad',CardType.SPELL,cost=1,keywords=(Keyword.MINI,)))
    def test_spec_and_queued_effect_require_strict_types(self):
        for keyword,card in (('twinspell','child'),(Keyword.ECHO,'child'),(Keyword.TWINSPELL,'')):
            with self.assertRaises(ValueError):HandDerivativeSpec(keyword,card)
        spec=HandDerivativeSpec(Keyword.TWINSPELL,'child')
        for pid,item in ((True,spec),(0,spec),(1,{})):
            with self.assertRaises(ValueError):CreatePlayDerivative(pid,item)
