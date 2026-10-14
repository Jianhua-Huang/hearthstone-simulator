"""Physical multi-zone targets and transformation lifecycle (R-098)."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from hs_sim.engine import (Game, Registry, CardDefinition, CardType, CardClass, CardMetadata,
    Rarity, Zone, Keyword, PlayerSetup, Scenario, PlayCard, SelectChoice, EndTurn, ResolutionError,
    SnapshotError, GenerationContext, PoolQuery, GenerationPolicy, MinionScope, BuffMinionsInZones,
    TransformMinionsInZones, TransformCapturedMinion, CardReference, MinionReference, CostSpec,
    TriggerSpec, AppendageSpec, SpellRepeatSpec, RewindSpec, CastSpell, minion_references)
from hs_sim.engine.effects import (Buff, Damage, Destroy, Summon, ReturnToHand, ChangeControl,
    Transform, Silence, CopyMinion, ChoiceOption, RequestChoice, GainArmor, ModifyCost, GrantKeyword,
    RevealHandCard, ReplaceHero, InvokeBehavior, Freeze)
from hs_sim.engine.hand_upgrades import BuffStoredCard, UpgradeHandCard
from hs_sim.engine.zones import MoveCard, CopyCard
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay

CTX=GenerationContext('cross-zone','experimental')


class CrossZoneTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('cross-zone-tests-v1')
        for cid,cls in (('mage',CardClass.MAGE),('warrior',CardClass.WARRIOR)):
            self.r.register_card(CardDefinition(cid,cid,CardType.HERO,health=30,metadata=CardMetadata(False,(cls,),None)))
        for cid,cost in (('a',1),('b',2),('c',4),('d',5),('e',7)):
            self.card(cid,cost=cost)
        self.card('plain-spell',kind=CardType.SPELL)
        self.pool()

    def card(self,cid,kind=CardType.MINION,classes=(CardClass.NEUTRAL,),tribes=(),executable=True,**kw):
        args=dict(attack=2,health=4) if kind==CardType.MINION else {}
        args.update(kw)
        definition=CardDefinition(cid,cid,kind,metadata=CardMetadata(True,classes,Rarity.COMMON,tribes=tribes),**args)
        if executable:self.r.register_card(definition)
        self.r.register_pool_card(PoolCard.from_definition(definition))
    def pool(self,name='pool',ids=('c','d','e')):
        self.r.register_pool(PoolDefinition(name,'v1',CTX.target_id,CTX.mode,tuple(PoolMember(i) for i in ids)))
    def script(self,fn,card='script',kind=CardType.SPELL,**kw):
        self.r.register_behavior('play.'+card,fn)
        self.r.register_card(CardDefinition(card,card,kind,on_play='play.'+card,health=4 if kind==CardType.MINION else 0,**kw))
    def watch(self,fn,event='stored_card_transformed'):
        self.r.register_behavior('watch',fn)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,cost=20,health=3,triggers=(TriggerSpec(event,'watch'),)))
    def scope(self,**kw):return MinionScope(query=PoolQuery(exclude_card_ids=('watch',)),**kw)
    def transform(self,**kw):return TransformMinionsInZones(1,'pool',3,scope=self.scope(),**kw)
    def game(self,hand=('script','a'),deck=('a',),board=('a',),enemy=(),context=CTX):
        return Game.from_scenario(Scenario((PlayerSetup('mage',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior',board=enemy,deck=('a',))),seed=58,generation_context=context),self.r)
    def play(self,g,cid='script'):
        g.apply(PlayCard(1,next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)))
    def cards(self,g,zone,player=1):return [g.state.entities[i] for i in getattr(g.state.players[player],zone)]
    def choose(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_buff_all_three_zones_and_not_enemy_or_spell(self):
        self.script(lambda c:[BuffMinionsInZones(1,3,3,source_id=c.source_id)])
        g=self.game(hand=('script','a','plain-spell'),enemy=('a',));self.play(g)
        for zone in ('hand','deck','board'):
            self.assertEqual([(e.attack,e.health) for e in self.cards(g,zone) if e.kind==CardType.MINION],[(5,7)])
        self.assertEqual(self.cards(g,'board',2)[0].attack,2);self.check(g)

    def test_physical_source_exclusion_keeps_other_same_card(self):
        self.script(lambda c:[BuffMinionsInZones(1,3,3,MinionScope(exclude_source=True),c.source_id)],kind=CardType.MINION)
        g=self.game(hand=('script','script'),deck=('script',),board=());self.play(g)
        self.assertEqual(self.cards(g,'board')[0].health,4)
        self.assertEqual(self.cards(g,'hand')[0].health,7);self.assertEqual(self.cards(g,'deck')[0].health,7);self.check(g)

    def test_scope_zone_order_and_physical_order(self):
        scope=MinionScope((Zone.BOARD,Zone.HAND,Zone.DECK))
        self.script(lambda c:[BuffMinionsInZones(1,1,1,scope,c.source_id)])
        g=self.game();ids=[self.cards(g,z)[-1].id for z in ('board','hand','deck')];self.play(g)
        self.assertEqual([e.target_id for e in g.events if e.kind in ('stats_changed','stored_card_buffed')],ids)

    def test_printed_tribe_cost_and_class_filters(self):
        self.card('beast',cost=1,tribes=('beast',),classes=(CardClass.MAGE,))
        scope=MinionScope(query=PoolQuery(tribes_any=('beast',),class_mode='current',max_cost=1))
        self.script(lambda c:[BuffMinionsInZones(1,3,3,scope,c.source_id)])
        g=self.game(hand=('script','a','beast'),board=('beast',));self.play(g)
        self.assertEqual([e.attack for e in self.cards(g,'hand')],[2,5]);self.assertEqual(self.cards(g,'board')[0].attack,5)

    def test_locations_and_dormant_minions_not_board_targets(self):
        self.card('sleep',dormant_turns=2)
        self.r.register_behavior('use.location',lambda c:[])
        self.r.register_card(CardDefinition('location','location',CardType.LOCATION,durability=2,on_use='use.location'))
        self.script(lambda c:[BuffMinionsInZones(1,3,3)])
        g=self.game(board=('a','sleep','location'));self.play(g)
        self.assertEqual([e.attack for e in self.cards(g,'board')[:2]],[5,2]);self.check(g)

    def test_new_summon_is_not_added_to_captured_batch(self):
        self.watch(lambda c:[Summon(1,'b')] if c.event.target_id!=c.source_id else [],event='stats_changed')
        self.script(lambda c:[BuffMinionsInZones(1,3,3,self.scope(zones=(Zone.BOARD,)))])
        g=self.game(board=('watch','a'));self.play(g)
        self.assertEqual(self.cards(g,'board')[-1].attack,2);self.check(g)

    def test_departed_later_target_is_not_pulled_back_for_buff(self):
        self.watch(lambda c:[ReturnToHand(c.state.players[1].board[-1])],event='stored_card_buffed')
        self.script(lambda c:[BuffMinionsInZones(1,3,3,self.scope())])
        g=self.game(board=('watch','a'),deck=());self.play(g)
        self.assertEqual([e.attack for e in self.cards(g,'hand')],[5,2]);self.check(g)

    def test_buff_source_death_does_not_cancel_later_targets(self):
        self.watch(lambda c:[Destroy(c.event.source_id)],event='stored_card_buffed')
        self.script(lambda c:[BuffMinionsInZones(1,3,3,self.scope(exclude_source=True),c.source_id)],kind=CardType.MINION)
        g=self.game(board=('watch','a'));self.play(g)
        self.assertEqual(self.cards(g,'deck')[0].attack,5);self.assertEqual(self.cards(g,'board')[-1].attack,5);self.check(g)

    def test_buffed_stored_minion_keeps_stats_when_played(self):
        self.script(lambda c:[BuffMinionsInZones(1,3,3)])
        g=self.game(board=());self.play(g);self.play(g,'a')
        self.assertEqual(self.cards(g,'board')[0].health,7);self.check(g)

    def test_silence_removes_board_batch_buff(self):
        self.script(lambda c:[BuffMinionsInZones(1,3,3),Silence(c.state.players[1].board[0])])
        g=self.game();self.play(g);self.assertEqual(self.cards(g,'board')[0].health,4)

    def test_transform_all_zones_keeps_physical_ids_and_acquisition(self):
        self.script(lambda c:[self.transform(source_id=c.source_id)])
        g=self.game();old=[self.cards(g,z)[-1] for z in ('hand','deck','board')];self.play(g)
        for zone,previous in zip(('hand','deck','board'),old):
            card=self.cards(g,zone)[0];self.assertEqual((card.id,card.card_id),(previous.id,'c'))
            self.assertEqual(card.zone_epoch,previous.zone_epoch+1)
        self.check(g)

    def test_stored_transform_resets_stats_keywords_and_cost_modifiers(self):
        def fn(c):
            entity=c.state.entities[c.state.players[1].hand[-1]];ref=CardReference.capture(entity)
            return [BuffStoredCard(ref,4,4),ModifyCost(entity.id,CostSpec(delta=-1)),
                    TransformCapturedMinion(ref,'c',c.source_id)]
        self.script(fn);g=self.game();self.play(g);card=self.cards(g,'hand')[0]
        self.assertEqual((card.attack,card.health,card.cost),(2,4,4));self.assertFalse(card.enchantments);self.check(g)

    def test_same_face_transformation_still_resets_and_invalidates_reference(self):
        def fn(c):
            ref=CardReference.capture(c.state.entities[c.state.players[1].hand[-1]])
            return [BuffStoredCard(ref,3,3),TransformCapturedMinion(ref,'a'),BuffStoredCard(ref,8,8)]
        self.script(fn);g=self.game();self.play(g);self.assertEqual(self.cards(g,'hand')[0].attack,2);self.check(g)

    def test_board_transform_clears_damage_frozen_and_granted_keyword(self):
        def fn(c):
            eid=c.state.players[1].board[0];ref=MinionReference.capture(c.state.entities[eid])
            return [Damage(eid,1),Freeze(eid),GrantKeyword(eid,Keyword.TAUNT),TransformCapturedMinion(ref,'c')]
        self.script(fn);g=self.game();self.play(g);e=self.cards(g,'board')[0]
        self.assertEqual(e.health,4);self.assertFalse(e.frozen);self.assertNotIn(Keyword.TAUNT,e.keywords);self.check(g)

    def test_printed_basis_ignores_discount(self):
        def fn(c):
            eid=c.state.players[1].hand[-1]
            return [ModifyCost(eid,CostSpec(set_to=2)),self.transform(cost_basis='printed')]
        self.script(fn);g=self.game();self.play(g);self.assertEqual(self.cards(g,'hand')[0].card_id,'c')

    def test_local_basis_and_separate_retained_printed_cost(self):
        def fn(c):
            eid=c.state.players[1].hand[-1]
            return [ModifyCost(eid,CostSpec(set_to=2)),self.transform(cost_basis='local',retain_cost_basis='printed')]
        self.script(fn);g=self.game();self.play(g);e=self.cards(g,'hand')[0]
        self.assertEqual((e.card_id,e.cost),('d',1));self.check(g)

    def test_printed_basis_and_retained_local_cost(self):
        def fn(c):
            eid=c.state.players[1].hand[-1]
            return [ModifyCost(eid,CostSpec(set_to=2)),self.transform(retain_cost_basis='local')]
        self.script(fn);g=self.game();self.play(g);e=self.cards(g,'hand')[0]
        self.assertEqual((e.card_id,e.cost),('c',2));self.check(g)

    def test_cost_is_installed_before_transformation_reaction(self):
        self.watch(lambda c:[GainArmor(1,c.state.entities[c.event.target_id].cost)],event='transformed')
        self.script(lambda c:[self.transform(retain_cost_basis='printed')]);g=self.game(board=('watch','a'))
        self.play(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)

    def test_pool_and_costs_are_captured_before_earlier_reaction(self):
        self.watch(lambda c:[ModifyCost(c.state.players[1].deck[0],CostSpec(set_to=4))]
                   if c.state.entities[c.event.target_id].zone==Zone.HAND else [])
        self.script(lambda c:[self.transform(cost_basis='local',retain_cost_basis='local')]);g=self.game(board=('watch',))
        self.play(g);self.assertEqual((self.cards(g,'deck')[0].card_id,self.cards(g,'deck')[0].cost),('c',1));self.check(g)

    def test_captured_class_survives_mid_batch_hero_replacement(self):
        self.card('mage-c',cost=4,classes=(CardClass.MAGE,));self.card('warrior-c',cost=4,classes=(CardClass.WARRIOR,))
        self.pool('class',('mage-c','warrior-c'))
        self.watch(lambda c:[ReplaceHero(1,'warrior')])
        self.script(lambda c:[TransformMinionsInZones(1,'class',3,self.scope(),PoolQuery(class_mode='current',include_neutral=False))])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual([self.cards(g,z)[0].card_id for z in ('hand','deck')],['mage-c','mage-c']);self.check(g)

    def test_missing_later_tier_fails_before_any_rng_or_mutation(self):
        self.card('missing',cost=5,executable=False);self.pool('mixed',('c','missing'))
        self.script(lambda c:[TransformMinionsInZones(1,'mixed',3)])
        g=self.game(deck=('b',));before=g.snapshot()
        with patch('hs_sim.engine.cross_zone.sample_candidates',side_effect=AssertionError('sampled before validation')):
            with self.assertRaisesRegex(ResolutionError,'missing'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_tier_skips_without_rng(self):
        self.script(lambda c:[TransformMinionsInZones(1,'pool',20)])
        g=self.game();before=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.cards(g,'hand')[0].card_id,'a');self.check(g)

    def test_empty_tier_can_be_explicit_error(self):
        self.script(lambda c:[TransformMinionsInZones(1,'pool',20,empty='error')]);g=self.game();before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Empty transformation'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_scope_still_requires_valid_generation_context(self):
        self.script(lambda c:[self.transform()]);g=self.game(hand=('script',),deck=(),board=(),context=None)
        with self.assertRaises(ResolutionError):self.play(g)

    def test_explicit_policy_permits_titan_transformation(self):
        from hs_sim.engine import ActivatedAbilitySpec
        self.r.register_behavior('noop',lambda c:[])
        self.card('titan',cost=4,keywords=(Keyword.TITAN,),activated_abilities=tuple(ActivatedAbilitySpec(str(i),'noop') for i in range(3)))
        self.pool('titans',('titan',))
        self.script(lambda c:[TransformMinionsInZones(1,'titans',3,policy=GenerationPolicy((Keyword.TITAN,)))])
        g=self.game();self.play(g);self.assertEqual(self.cards(g,'hand')[0].card_id,'titan');self.check(g)

    def test_source_removed_does_not_cancel_captured_transforms(self):
        self.watch(lambda c:[Destroy(c.event.source_id)])
        self.script(lambda c:[self.transform(source_id=c.source_id)],kind=CardType.MINION)
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.cards(g,'deck')[0].card_id,'c');self.check(g)

    def test_later_departed_target_skips_without_extra_rng(self):
        self.watch(lambda c:[ReturnToHand(c.state.players[1].board[-1])])
        self.script(lambda c:[self.transform()]);g=self.game(deck=(),board=('watch','a'))
        from hs_sim.engine.pools import sample_candidates
        with patch('hs_sim.engine.cross_zone.sample_candidates',wraps=sample_candidates) as sample:
            self.play(g);self.assertEqual(sample.call_count,1)
        self.assertEqual([e.card_id for e in self.cards(g,'hand')],['c','a']);self.check(g)

    def test_control_change_invalidates_board_reference(self):
        def fn(c):
            ref=MinionReference.capture(c.state.entities[c.state.players[1].board[0]])
            return [ChangeControl(ref.entity_id,2),ChangeControl(ref.entity_id,1),TransformCapturedMinion(ref,'c')]
        self.script(fn);g=self.game();self.play(g);self.assertEqual(self.cards(g,'board')[0].card_id,'a');self.check(g)

    def test_zone_exit_and_return_invalidates_stored_reference(self):
        def fn(c):
            ref=CardReference.capture(c.state.entities[c.state.players[1].hand[-1]])
            return [MoveCard(ref,1,Zone.DECK),TransformCapturedMinion(ref,'c')]
        self.script(fn);g=self.game();self.play(g);self.assertEqual(self.cards(g,'deck')[-1].card_id,'a');self.check(g)

    def test_colossal_only_expands_on_board(self):
        self.card('limb',cost=0)
        self.card('giant',cost=4,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        self.pool('giants',('giant',));self.script(lambda c:[TransformMinionsInZones(1,'giants',3)])
        g=self.game();self.play(g)
        self.assertEqual([e.card_id for e in self.cards(g,'board')],['giant','limb'])
        self.assertEqual(len(g.state.colossal_history),1);self.check(g)

    def test_full_board_transform_preserves_slots_and_skips_extra_limb(self):
        self.card('limb');self.card('giant',cost=4,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        self.pool('giants',('giant',));self.script(lambda c:[TransformMinionsInZones(1,'giants',3)])
        g=self.game(board=('a',)*7);self.play(g)
        self.assertEqual([e.card_id for e in self.cards(g,'board')],['giant']*7);self.check(g)

    def test_no_battlecry_or_summon_for_stored_transforms(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,9)])
        self.card('bc',cost=4,on_play='armor');self.pool('bc',('bc',))
        self.script(lambda c:[TransformMinionsInZones(1,'bc',3)])
        g=self.game(board=());self.play(g)
        self.assertFalse(any(e.kind=='minion_summoned' for e in g.events));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_stored_transform_to_dormant_is_awake_until_summoned(self):
        self.card('sleep',cost=4,dormant_turns=2);self.pool('sleep',('sleep',))
        self.script(lambda c:[TransformMinionsInZones(1,'sleep',3)]);g=self.game();self.play(g)
        self.assertIsNone(self.cards(g,'hand')[0].dormancy);self.assertIsNotNone(self.cards(g,'board')[0].dormancy);self.check(g)

    def test_private_transformation_forgets_previously_revealed_hand_face(self):
        def fn(c):
            eid=c.state.players[1].hand[-1]
            return [RevealHandCard(eid,(2,)),self.transform()]
        self.script(fn);g=self.game();self.play(g)
        other=g.observe(2);own=next(p for p in other['players'] if p['id']==1)
        self.assertIsNone(own['hand'][0]['card_id'])
        self.assertFalse(any(e['kind']=='stored_card_transformed' for e in g.player_events(2)));self.check(g)

    def test_deck_identity_stays_hidden_from_both_players(self):
        self.script(lambda c:[self.transform()]);g=self.game(board=(),hand=('script',));self.play(g)
        for viewer in (1,2):
            self.assertFalse(any(e['kind']=='stored_card_transformed' for e in g.player_events(viewer)))
        self.check(g)

    def test_mid_batch_choice_restore_retains_pending_targets_and_rng(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        self.script(lambda c:[self.transform()]);g=self.game(board=('watch','a'))
        self.play(g);self.assertEqual(self.cards(g,'hand')[0].card_id,'c');self.assertEqual(self.cards(g,'deck')[0].card_id,'a')
        self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            while match.state.pending_choice:self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_corrupt_pending_destination_pool_is_rejected(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        self.script(lambda c:[self.transform()]);g=self.game(board=('watch',));self.play(g)
        snap=g.snapshot()
        def alter(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.TransformPoolTarget'):value['fields']['pool_id']='missing'
                for child in value.values():alter(child)
            elif isinstance(value,list):
                for child in value:alter(child)
        alter(snap)
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_late_exception_rolls_back_submitted_choice_only(self):
        self.r.register_behavior('late.fail',lambda c:[TransformCapturedMinion(
            CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),'plain-spell')])
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('fail','fail',(
            InvokeBehavior('late.fail',c.source_id,1),)),),c.source_id)])
        self.script(lambda c:[self.transform()]);g=self.game(board=('watch',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before)

    def test_lethal_reaction_abandons_remaining_transformations(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,50)])
        self.script(lambda c:[self.transform()]);g=self.game(board=('watch','a'));self.play(g)
        self.assertEqual(self.cards(g,'deck')[0].card_id,'a');self.assertFalse(g.state.pending_choice);self.check(g)

    def test_auto_cast_runs_cross_zone_batch(self):
        self.script(lambda c:[self.transform()],card='body')
        self.script(lambda c:[CastSpell(1,'body',c.source_id)])
        g=self.game();self.play(g);self.assertEqual(self.cards(g,'hand')[0].card_id,'c');self.check(g)

    def test_spell_repeat_recaptures_transformed_faces(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,cost=20,health=3,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.script(lambda c:[self.transform()]);g=self.game(board=('repeat',));self.play(g)
        self.assertEqual(self.cards(g,'hand')[0].card_id,'e');self.check(g)

    def test_rewind_undoes_all_zones_before_retry(self):
        self.script(lambda c:[self.transform()],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game();self.play(g);choice=g.state.pending_choice
        retry=next(o.id for o in choice.options if 'retry' in o.id)
        g.apply(SelectChoice(1,choice.id,(retry,)))
        self.assertEqual(self.cards(g,'hand')[0].card_id,'c');self.check(g)

    def test_player_port_can_submit_cross_zone_effect(self):
        self.script(lambda c:[self.transform()]);g=self.game();port=g.for_player(1);listing=port.legal_actions()
        own=next(p for p in listing['observation']['players'] if p['id']==1)
        ref=next(e['ref'] for e in own['hand'] if e['card_id']=='script')
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref)
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.check(g)

    def test_invalid_declarations_rejected(self):
        for fields in ({'zones':[]},{'zones':(Zone.BOARD,Zone.BOARD)},{'zones':(Zone.GRAVEYARD,)},
                       {'exclude_source':1},{'query':PoolQuery(exclude_source=True)}):
            with self.assertRaises(ValueError):MinionScope(**fields)
        for fields in ({'cost_delta':True},{'cost_basis':'paid'},{'retain_cost_basis':'quoted'},
                       {'query':PoolQuery(min_cost=3)},{'query':PoolQuery(kinds=(CardType.SPELL,))},{'empty':'whiteboard'}):
            with self.assertRaises(ValueError):TransformMinionsInZones(1,'pool',**fields)

    def test_copy_current_keeps_retained_cost_and_new_attachment_ids(self):
        self.script(lambda c:[self.transform(retain_cost_basis='printed'),InvokeBehavior('copy.result',c.source_id,1)])
        self.r.register_behavior('copy.result',lambda c:[CopyCard(CardReference.capture(
            c.state.entities[c.state.players[1].hand[-1]]),1,mode='current')])
        g=self.game();self.play(g);a,b=self.cards(g,'hand')
        self.assertEqual((a.card_id,b.card_id,a.cost,b.cost),('c','c',1,1))
        self.assertNotEqual(a.id,b.id);self.assertNotEqual(a.enchantments[0].id,b.enchantments[0].id);self.check(g)

    def test_bounce_transformed_minion_resets_retained_cost(self):
        self.script(lambda c:[self.transform(retain_cost_basis='printed'),ReturnToHand(c.state.players[1].board[0])])
        g=self.game();self.play(g);self.assertEqual((self.cards(g,'hand')[-1].card_id,self.cards(g,'hand')[-1].cost),('c',4));self.check(g)

    def test_transformation_does_not_create_death_history(self):
        self.r.register_behavior('death',lambda c:[GainArmor(1,8)])
        self.card('reborn',cost=1,keywords=(Keyword.REBORN,),deathrattle='death')
        self.script(lambda c:[self.transform()]);g=self.game(board=('reborn',));self.play(g)
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.check(g)

    def test_source_exclusion_requires_source_even_when_scope_empty(self):
        self.script(lambda c:[BuffMinionsInZones(1,1,1,MinionScope(exclude_source=True))])
        g=self.game(hand=('script',),deck=(),board=())
        with self.assertRaisesRegex(ResolutionError,'source'):self.play(g)

    def test_temporary_stored_state_is_reset_by_transformation(self):
        from hs_sim.engine.temporary_cards import CreateTemporaryCard
        # Generated hand lifetime is reset along with the original transformed face.
        self.script(lambda c:[CreateTemporaryCard(1,'a',c.state.turn,source_id=c.source_id),
            CreateTemporaryCard(1,'a',c.state.turn,source_id=c.source_id),InvokeBehavior('transform.generated',c.source_id,1)])
        self.r.register_behavior('transform.generated',lambda c:[TransformCapturedMinion(
            CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),'c')])
        g=self.game(hand=('script',));self.play(g)
        self.assertIsNotNone(self.cards(g,'hand')[0].hand_lifetime);self.assertIsNone(self.cards(g,'hand')[1].hand_lifetime)
        g.apply(EndTurn(1));self.assertEqual([c.card_id for c in self.cards(g,'hand')],['c']);self.check(g)

    def test_default_policy_leaves_titan_only_tier_empty(self):
        from hs_sim.engine import ActivatedAbilitySpec
        self.r.register_behavior('noop',lambda c:[])
        self.card('titan',cost=4,keywords=(Keyword.TITAN,),activated_abilities=tuple(ActivatedAbilitySpec(str(i),'noop') for i in range(3)))
        self.pool('titans',('titan',));self.script(lambda c:[TransformMinionsInZones(1,'titans',3)])
        g=self.game();before=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.cards(g,'hand')[0].card_id,'a');self.check(g)

    def test_captured_batch_cannot_bypass_resolution_budget(self):
        from hs_sim.engine import Ruleset, ResolutionLimitExceeded
        self.script(lambda c:[self.transform()])
        g=Game.from_scenario(Scenario((PlayerSetup('mage',hand=('script',),deck=('a',)*20),
            PlayerSetup('warrior')),seed=58,generation_context=CTX),self.r,Ruleset(max_resolution_steps=8))
        before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)


class CrossZoneRewardTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand,board=('CS2_182',),deck=('CS2_182',)):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=58,generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)
    def play(self,g,cid):g.apply(PlayCard(1,next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)))
    def test_dragon_buffs_all_other_physical_minions_in_three_zones(self):
        g=self.game(('DEEP_999t4','CS2_182'));self.play(g,'DEEP_999t4')
        for eid in (g.state.players[1].hand[0],g.state.players[1].deck[0],g.state.players[1].board[0]):
            e=g.state.entities[eid];self.assertEqual((e.attack,e.health),(7,8))
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].attack,5)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_murloc_changes_three_zones_and_retains_printed_cost(self):
        g=self.game(('DEEP_999t5','CS2_182'));self.play(g,'DEEP_999t5')
        for eid in (g.state.players[1].hand[0],g.state.players[1].deck[0],g.state.players[1].board[0]):
            e=g.state.entities[eid];self.assertEqual((e.card_id,e.cost),('CS2_222',4))
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id,'DEEP_999t5')
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_all_top_rewards_have_explicit_adapters(self):
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS
        self.assertEqual(set(EXCAVATE_CLASS_REWARDS.values())-set(self.r.cards),set())
    def test_transformation_sample_pool_is_explicitly_incomplete(self):
        from hs_sim.engine.representative import EXCAVATE_TRANSFORM_POOL_ID, EXCAVATE_TRANSFORM_SAMPLE_IDS
        pool=self.r.pool(EXCAVATE_TRANSFORM_POOL_ID,GenerationContext('local-2026-09-23','experimental'))
        self.assertFalse(pool.complete);self.assertEqual(tuple(m.card_id for m in pool.members),EXCAVATE_TRANSFORM_SAMPLE_IDS)


if __name__=='__main__':unittest.main()
