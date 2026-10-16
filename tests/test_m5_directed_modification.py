"""Physical random modifications and directed transforms, including power use."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (CardDefinition,CardType,CardMetadata,CardClass,Rarity,Registry,Game,
    PlayerSetup,Scenario,PlayCard,UseHeroPower,EndTurn,SelectChoice,TriggerSpec,TriggerHeroPower,
    Keyword,RewindSpec,IllegalAction,ResolutionError,SnapshotError,GenerationContext,PoolQuery,
    RandomBuffStoredMinion,TransformMinionFromPool,MinionReference,CardReference,CostSpec,Zone)
from hs_sim.engine.effects import (GainArmor,Damage,ReplaceHeroPower,Summon,Transform,ReturnToHand,
    Silence,Destroy,RequestChoice,ChoiceOption,RefreshHeroPower,ChangeControl,ModifyCost,InvokeBehavior)
from hs_sim.engine.hand_upgrades import BuffStoredCard,UpgradeHandCard
from hs_sim.engine.zones import MoveCard,CopyCard,DiscardCard
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
CTX=GenerationContext('directed','experimental')


class DirectedModificationTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('directed-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.MAGE,),None)))
        for cid,cost,tribes in (('beast',3,('beast',)),('other',1,()),('dual',3,('beast','undead')),
                               ('all',3,('all',)),('four',4,()),('five',5,()),('zero',0,())):
            self.card(cid,cost,tribes)
        self.pool()
        self.script('buff',lambda c:[RandomBuffStoredMinion(1,2,query=PoolQuery(tribes_any=('beast',)),
            source_id=c.source_id,cost=CostSpec(delta=-2))])
        self.script('evolve',lambda c:[self.evolve(c)])
    def card(self,cid,cost,tribes=(),executable=True,**kw):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=4,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes),**kw)
        if executable:self.r.register_card(d)
        self.r.register_pool_card(PoolCard.from_definition(d))
    def pool(self,pid='pool',ids=('zero','four','five')):
        self.r.register_pool(PoolDefinition(pid,'v1',CTX.target_id,CTX.mode,tuple(PoolMember(i) for i in ids)))
    def script(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**kw))
    def watch(self,fn,event='stored_card_buffed'):
        self.r.register_behavior('watch',fn)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=4,
            triggers=(TriggerSpec(event,'watch'),),metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    def power(self,cid,fn,target=False,**kw):
        from hs_sim.engine import TargetSpec,TargetMode
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid,
            targeting=TargetSpec(TargetMode.REQUIRED,kinds=(CardType.MINION,),relation='friendly') if target else None,**kw))
    def game(self,hand=('buff','beast'),board=(),deck=('beast',),enemy=(),power=None,context=CTX):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=deck,
            hero_power_card_id=power,mana=10,max_mana=10),PlayerSetup('hero',board=enemy,deck=('other',)*3)),
            seed=64,generation_context=context),self.r)
    def play(self,g,cid='buff'):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def choose(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def entity(self,g,zone='hand',index=-1):return g.state.entities[getattr(g.state.players[1],zone)[index]]
    def evolve(self,c,**kw):
        e=c.state.entities[c.target_id or c.state.players[1].board[-1]]
        return TransformMinionFromPool(MinionReference.capture(e),'pool',1,source_id=c.source_id,**kw)
    def ref(self,c):return CardReference.capture(c.state.entities[c.state.players[1].hand[-1]])
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_one_physical_beast_receives_both_modifiers(self):
        g=self.game(hand=('buff','beast','beast','other'));self.play(g)
        self.assertEqual(sorted((g.state.entities[i].attack,g.state.entities[i].cost) for i in g.state.players[1].hand),[(2,1),(2,3),(4,1)])
        self.check(g)
    def test_dual_and_all_tribes_are_eligible(self):
        for cid in ('dual','all'):
            with self.subTest(cid=cid):
                g=self.game(hand=('buff',cid));self.play(g);self.assertEqual((self.entity(g).attack,self.entity(g).cost),(4,1));self.check(g)
    def test_empty_filter_skips_rng_and_continues(self):
        self.script('empty',lambda c:[RandomBuffStoredMinion(1,3,query=PoolQuery(tribes_any=('beast',))),GainArmor(1,2)])
        g=self.game(hand=('empty','other'));rng=g._rng.getstate();self.play(g,'empty')
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)
    def test_full_hand_is_modified_without_burning_or_creating(self):
        self.power('power',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2))])
        g=self.game(hand=('beast',)*10,power='power');ids=g.state.players[1].hand
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(g.state.players[1].hand,ids)
        self.assertEqual(sum(g.state.entities[i].attack==4 for i in ids),1);self.check(g)
    def test_deck_selection_is_private_to_both_players(self):
        self.script('deck',lambda c:[RandomBuffStoredMinion(1,2,zone=Zone.DECK,cost=CostSpec(delta=-2))])
        g=self.game(hand=('deck',));self.play(g,'deck');self.assertEqual((self.entity(g,'deck').attack,self.entity(g,'deck').cost),(4,1))
        for p in (1,2):self.assertFalse(any(e['kind']=='stored_card_buffed' for e in g.player_events(p)))
        self.check(g)
    def test_hand_identity_and_buff_event_do_not_leak(self):
        g=self.game();self.play(g)
        self.assertTrue(any(e['kind']=='stored_card_buffed' for e in g.player_events(1)))
        self.assertFalse(any(e['kind']=='stored_card_buffed' for e in g.player_events(2)))
        own=next(p for p in g.observe(2)['players'] if p['id']==1)
        self.assertIsNone(own['hand'][0]['card_id']);self.check(g)
    def test_reactions_see_attack_and_cost_committed_together(self):
        self.watch(lambda c:[GainArmor(1,c.state.entities[c.event.target_id].attack*10+c.state.entities[c.event.target_id].cost)])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,41);self.check(g)
    def test_cost_only_modification_is_not_discarded(self):
        self.script('cost',lambda c:[BuffStoredCard(self.ref(c),cost=CostSpec(delta=-5))])
        g=self.game(hand=('cost','beast'));self.play(g,'cost');self.assertEqual((self.entity(g).attack,self.entity(g).cost),(2,0));self.check(g)
    def test_inapplicable_cost_filter_fails_before_random_selection(self):
        self.script('bad',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(card_ids=('beast',),delta=-1))])
        g=self.game(hand=('bad','beast','other'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)
    def test_unknown_tribe_metadata_rolls_back(self):
        self.r.register_card(CardDefinition('unknown','unknown',CardType.MINION,health=1))
        g=self.game(hand=('buff','unknown'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)
    def test_expired_modification_rejected_even_without_candidates(self):
        self.script('old',lambda c:[RandomBuffStoredMinion(1,2,expires_turn=1)])
        g=self.game(hand=('old',),deck=('other',));g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'old')
        self.assertEqual(g.snapshot(),before)
    def test_stat_and_cost_expire_together(self):
        self.script('temp',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2),expires_turn=c.state.turn)])
        g=self.game(hand=('temp','beast'));self.play(g,'temp');eid=self.entity(g).id
        g.apply(EndTurn(1));e=g.state.entities[eid];self.assertEqual((e.attack,e.cost),(2,3));self.check(g)
    def test_copy_current_preserves_both_with_independent_attachments(self):
        self.script('copy',lambda c:[CopyCard(self.ref(c),1)])
        g=self.game(hand=('buff','copy','beast'));self.play(g);self.play(g,'copy')
        a,b=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual((a.attack,a.cost,b.attack,b.cost),(4,1,4,1))
        self.assertFalse({e.id for e in a.enchantments}&{e.id for e in b.enchantments});self.check(g)
    def test_play_then_silence_clears_both_modifiers(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[-1])])
        g=self.game(hand=('buff','silence','beast'));self.play(g);eid=self.play(g,'beast')
        self.assertEqual(g.state.players[1].mana,9);self.play(g,'silence')
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].cost),(2,3));self.check(g)
    def test_guarded_buff_skips_changed_face_and_does_not_apply_cost(self):
        self.script('stale',lambda c:[UpgradeHandCard(self.ref(c),'other'),BuffStoredCard(self.ref(c),2,cost=CostSpec(delta=-2))])
        g=self.game(hand=('stale','beast'));self.play(g,'stale');self.assertEqual((self.entity(g).attack,self.entity(g).cost),(2,1));self.check(g)
    def test_buff_skips_card_moved_to_another_zone(self):
        self.script('move',lambda c:[MoveCard(self.ref(c),1,Zone.DECK),BuffStoredCard(self.ref(c),2,cost=CostSpec(delta=-2))])
        g=self.game(hand=('move','beast'));self.play(g,'move');self.assertEqual((self.entity(g,'deck').attack,self.entity(g,'deck').cost),(2,3));self.check(g)
    def test_mid_choice_restores_modified_card_without_second_roll(self):
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),),c.source_id)])
        g=self.game(board=('watch',));self.play(g);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)
    def test_failed_followup_rolls_back_random_and_both_attachments(self):
        self.script('bad',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2)),Summon(1,'missing')])
        g=self.game(hand=('bad','beast'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)
    def test_only_directed_board_target_transforms(self):
        g=self.game(hand=('evolve','beast'),board=('beast','beast'));ids=g.state.players[1].board
        self.play(g,'evolve');self.assertEqual([g.state.entities[i].card_id for i in ids],['beast','four'])
        self.assertEqual(self.entity(g).card_id,'beast');self.check(g)
    def test_targeted_stored_transform_and_retained_cost(self):
        self.script('stored',lambda c:[TransformMinionFromPool(self.ref(c),'pool',1,retain_cost_basis='printed')])
        g=self.game(hand=('stored','beast'));eid=self.entity(g).id;self.play(g,'stored')
        self.assertEqual((self.entity(g).id,self.entity(g).card_id,self.entity(g).cost),(eid,'four',3));self.check(g)
    def test_printed_and_local_cost_basis_are_distinct(self):
        for basis in ('printed','local'):
            self.script('cost-'+basis,lambda c,b=basis:[ModifyCost(c.state.players[1].board[-1],CostSpec(delta=1)),self.evolve(c,cost_basis=b)])
        for basis,expected in (('printed','four'),('local','five')):
            with self.subTest(basis=basis):
                g=self.game(hand=('cost-'+basis,),board=('beast',));self.play(g,'cost-'+basis)
                self.assertEqual(self.entity(g,'board').card_id,expected);self.check(g)
    def test_negative_tier_clamps_to_zero(self):
        self.script('zero-tier',lambda c:[replace(self.evolve(c),cost_delta=-20)])
        g=self.game(hand=('zero-tier',),board=('beast',));self.play(g,'zero-tier');self.assertEqual(self.entity(g,'board').card_id,'zero');self.check(g)
    def test_stale_target_does_not_consume_rng_or_hit_returned_minion(self):
        self.script('stale-board',lambda c:[ReturnToHand(c.state.players[1].board[-1]),self.evolve(c)])
        g=self.game(hand=('stale-board',),board=('beast',));rng=g._rng.getstate();self.play(g,'stale-board')
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.entity(g).card_id,'beast');self.check(g)
    def test_control_change_away_and_back_invalidates_reference(self):
        self.script('control',lambda c:[ChangeControl(c.state.players[1].board[-1],2),ChangeControl(c.state.players[1].board[-1],1),self.evolve(c)])
        g=self.game(hand=('control',),board=('beast',));self.play(g,'control');self.assertEqual(self.entity(g,'board').card_id,'beast');self.check(g)
    def test_same_card_transform_invalidates_old_reference(self):
        self.script('same',lambda c:[Transform(c.state.players[1].board[-1],'beast'),self.evolve(c)])
        g=self.game(hand=('same',),board=('beast',));self.play(g,'same');self.assertEqual(self.entity(g,'board').card_id,'beast');self.check(g)
    def test_empty_tier_skip_does_not_roll(self):
        g=self.game(hand=('evolve',),board=('five',));rng=g._rng.getstate();self.play(g,'evolve')
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.entity(g,'board').card_id,'five');self.check(g)
    def test_empty_tier_error_rolls_back(self):
        self.script('strict',lambda c:[self.evolve(c,empty='error')])
        g=self.game(hand=('strict',),board=('five',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'strict')
        self.assertEqual(g.snapshot(),before)
    def test_missing_eligible_definition_is_not_filtered(self):
        self.card('missing',4,executable=False);self.pool('missing-pool',('four','missing'))
        self.script('missing-cast',lambda c:[replace(self.evolve(c),pool_id='missing-pool')])
        g=self.game(hand=('missing-cast',),board=('beast',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'missing-cast')
        self.assertEqual(g.snapshot(),before)
    def test_missing_pool_rejected_even_after_target_departs(self):
        self.script('bad-pool',lambda c:[ReturnToHand(c.state.players[1].board[-1]),replace(self.evolve(c),pool_id='absent')])
        g=self.game(hand=('bad-pool',),board=('beast',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad-pool')
        self.assertEqual(g.snapshot(),before)
    def test_missing_context_is_explicit_error(self):
        g=self.game(hand=('evolve',),board=('beast',),context=None);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'evolve')
        self.assertEqual(g.snapshot(),before)
    def test_dormant_target_is_not_transformed(self):
        self.card('dormant',3,dormant_turns=2)
        g=self.game(hand=('evolve',),board=('dormant',));self.play(g,'evolve');self.assertEqual(self.entity(g,'board').card_id,'dormant');self.check(g)
    def test_full_board_reuses_target_slot(self):
        g=self.game(hand=('evolve',),board=('beast',)*7);ids=g.state.players[1].board
        self.play(g,'evolve');self.assertEqual(g.state.players[1].board,ids)
        self.assertEqual(sum(g.state.entities[i].card_id=='four' for i in ids),1);self.check(g)
    def test_targeted_power_uses_common_target_validation(self):
        self.power('wind',lambda c:[self.evolve(c)],True)
        g=self.game(hand=(),board=('beast',),enemy=('beast',),power='wind');power=g.state.players[1].hero_power_id
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,power,g.state.players[2].board[0]))
        g.apply(UseHeroPower(1,power,g.state.players[1].board[0]));self.assertEqual(self.entity(g,'board').card_id,'four');self.check(g)
    def test_power_target_removed_in_start_reaction_skips(self):
        self.power('wind',lambda c:[self.evolve(c)],True)
        self.watch(lambda c:[ReturnToHand(c.event.target_id)],'hero_power_started')
        g=self.game(hand=(),board=('watch','beast'),power='wind');rng=g._rng.getstate()
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[1].board[-1]))
        self.assertEqual(self.entity(g).card_id,'beast');self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,8);self.check(g)
    def test_choice_before_targeted_transform_restores_reference(self):
        self.script('choice',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),)),self.evolve(c)])
        g=self.game(hand=('choice',),board=('beast',));self.play(g,'choice');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.entity(g,'board').card_id,'four');self.check(g)
    def test_corrupt_pending_transform_pool_fails_restore(self):
        self.script('choice',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),)),self.evolve(c)])
        g=self.game(hand=('choice',),board=('beast',));self.play(g,'choice');s=g.snapshot()
        def alter(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.TransformMinionFromPool'):v['fields']['pool_id']='absent'
                for x in v.values():alter(x)
            elif isinstance(v,list):
                for x in v:alter(x)
        alter(s);self.reject(s)
    def test_lethal_reaction_stops_later_work(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,50)],'stored_card_buffed')
        self.script('both',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2)),self.evolve(c)])
        g=self.game(hand=('both','beast'),board=('watch','beast'));self.play(g,'both')
        self.assertEqual(self.entity(g,'board').card_id,'beast');self.check(g)
    def test_rewind_restores_original_cost_and_attack_before_retry(self):
        self.script('rewind',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2))],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind','beast'));self.play(g,'rewind');c=g.state.pending_choice
        g.apply(SelectChoice(1,c.id,(next(o.id for o in c.options if 'retry' in o.id),)))
        self.assertEqual((self.entity(g).attack,self.entity(g).cost),(4,1));self.check(g)
    def test_invalid_declarations_are_rejected(self):
        for kw in ({'zone':Zone.BOARD},{'health':-1},{'attack':True},{'cost':{}},{'query':PoolQuery(kinds=(CardType.SPELL,))}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):RandomBuffStoredMinion(1,**kw)
        ref=CardReference(1,1,Zone.HAND,'beast',0)
        for kw in ({'cost_basis':'paid'},{'query':PoolQuery(min_cost=1)},{'empty':'fallback'},{'cost_delta':True}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):TransformMinionFromPool(ref,'pool',**kw)
    def test_old_schema63_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=63;self.reject(s)

    def test_random_hand_candidates_read_when_effect_runs(self):
        self.power('wolf',lambda c:[RandomBuffStoredMinion(1,2,query=PoolQuery(tribes_any=('beast',)),cost=CostSpec(delta=-2))])
        self.watch(lambda c:[DiscardCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]))],
            'hero_power_started')
        g=self.game(hand=('beast','dual'),board=('watch',),power='wolf');remaining=g.state.players[1].hand[-1]
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.state.players[1].hand,[remaining]);self.assertEqual(self.entity(g).attack,4);self.check(g)

    def test_power_replacement_does_not_cancel_started_hand_modification(self):
        self.power('wolf',lambda c:[RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2))])
        self.power('new',lambda c:[])
        self.watch(lambda c:[ReplaceHeroPower(1,'new')],'hero_power_started')
        g=self.game(hand=('beast',),board=('watch',),power='wolf');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.entity(g).attack,4);self.assertEqual(g.state.hero_power_history[0].card_id,'wolf');self.check(g)

    def test_pending_random_selection_restores_before_drawing_rng(self):
        self.script('choice-random',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),)),RandomBuffStoredMinion(1,2,cost=CostSpec(delta=-2))])
        g=self.game(hand=('choice-random','beast','dual'));self.play(g,'choice-random');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_failed_choice_restores_committed_hand_modification(self):
        self.r.register_behavior('late-fail',lambda c:[Summon(1,'absent')])
        self.watch(lambda c:[RequestChoice(1,(ChoiceOption('bad','bad',(InvokeBehavior('late-fail',c.source_id,1),)),),c.source_id)])
        g=self.game(board=('watch',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_frozen_pool_target_keeps_tier_after_local_cost_changes(self):
        from hs_sim.engine.cross_zone import TransformPoolTarget
        self.script('freeze-tier',lambda c:[RequestChoice(1,(ChoiceOption('change','change',(
            ModifyCost(c.state.players[1].board[-1],CostSpec(set_to=8)),)),)),
            TransformPoolTarget(MinionReference.capture(c.state.entities[c.state.players[1].board[-1]]),'pool',
                PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4),
                self.evolve(c).policy, c.player_id)])
        g=self.game(hand=('freeze-tier',),board=('beast',));self.play(g,'freeze-tier');self.check(g);self.choose(g)
        self.assertEqual(self.entity(g,'board').card_id,'four');self.check(g)

    def test_transform_never_fires_battlecry_or_deathrattle(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,7)])
        self.card('death',3,deathrattle='armor');self.card('battlecry',4,on_play='armor');self.pool('battlecry',('battlecry',))
        self.script('no-triggers',lambda c:[replace(self.evolve(c),pool_id='battlecry')])
        g=self.game(hand=('no-triggers',),board=('death',));self.play(g,'no-triggers')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertFalse(g.state.death_history);self.check(g)


class DirectedRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    play=DirectedModificationTests.play
    check=DirectedModificationTests.check
    entity=DirectedModificationTests.entity
    def game(self,hero='HERO_05',hand=('EDR_852','LOE_029'),board=(),power=None):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,hero_power_card_id=power,
            deck=('LOE_029',)*3,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*3)),seed=64,
            generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)
    def use(self,g,target=None):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target))
    def test_hunter_growth_scales_attack_and_discount(self):
        g=self.game(hand=('EDR_852','EDR_852','LOE_029'));self.play(g,'EDR_852');self.play(g,'EDR_852');self.use(g)
        self.assertEqual((self.entity(g).attack,self.entity(g).cost),(3,0));self.assertEqual(g.state.players[1].mana,4);self.check(g)
    def test_hunter_no_beast_still_uses_power_without_rng(self):
        g=self.game(hand=(),power='EDR_850p');rng=g._rng.getstate();self.use(g)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,8);self.check(g)
    def test_hunter_can_buff_uncollectible_beast(self):
        g=self.game(hand=('TSC_216t',),power='EDR_850p');self.use(g)
        self.assertEqual(self.entity(g).attack,self.r.card('TSC_216t').attack+1);self.check(g)
    def test_wind_only_changes_selected_friendly_minion(self):
        g=self.game('HERO_02',board=('CS2_182','LOE_029'));self.play(g,'EDR_852')
        target=g.state.players[1].board[0];self.use(g,target)
        self.assertEqual(g.state.entities[target].card_id,'BOT_563');self.assertEqual(self.entity(g,'board').card_id,'EDR_852');self.check(g)
    def test_wind_growth_changes_destination_tier(self):
        g=self.game('HERO_02',hand=('EDR_852','EDR_852'),board=('CS2_182',));self.play(g,'EDR_852');self.play(g,'EDR_852')
        target=g.state.players[1].board[0];self.use(g,target)
        self.assertEqual(g.state.entities[target].card_id,'ULD_208');self.check(g)
    def test_wind_empty_board_has_no_manual_action(self):
        g=self.game('HERO_02',hand=(),power='EDR_448p')
        self.assertFalse(any(isinstance(a,UseHeroPower) for a in g.legal_actions()));self.check(g)
    def test_wisprider_triggers_hunter_without_consuming_use(self):
        g=self.game(hand=('EDR_519','LOE_029'));self.play(g,'EDR_519')
        self.assertEqual(g.state.hero_power_history[0].origin,'effect');self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0)
        self.assertEqual(self.entity(g).attack,2);self.check(g)
    def test_wisprider_triggers_wind_on_available_friendly_target(self):
        g=self.game('HERO_02',hand=('EDR_519',));self.play(g,'EDR_519')
        self.assertEqual(g.state.hero_power_history[0].origin,'effect');self.assertIsNone(g.state.hero_power_history[0].failure);self.check(g)
    def test_all_declared_imbue_skills_have_adapters(self):
        from hs_sim.engine.representative import IMBUE_CLASS_POWERS
        self.assertEqual({c for c in IMBUE_CLASS_POWERS.values() if c not in self.r.cards},set())
    def test_default_hunter_shaman_powers_not_silently_substituted(self):
        from hs_sim.engine import DeckPolicy,DeckSpec,validate_deck
        for hero,cls,power in (('HERO_05',CardClass.HUNTER,'EDR_850p'),('HERO_02',CardClass.SHAMAN,'EDR_448p')):
            with self.subTest(hero=hero):
                self.assertIsNone(self.r.card(hero).initial_hero_power)
                report=validate_deck(DeckSpec(hero,power,cls,('LOE_029',)),self.r,
                    DeckPolicy('test','test','experimental',('LOE_029',),deck_size=1))
                self.assertIn('hero_power',[i.code for i in report.issues])

    def test_player_port_example_restores_and_replays(self):
        from examples.imbue_directed_modification import run
        g,s=run();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertEqual(len(g.state.hero_power_history),2)


if __name__=='__main__':unittest.main()
