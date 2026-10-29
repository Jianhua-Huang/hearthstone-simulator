"""Actual Rune budget roots and three-owner-end physical Tower casts."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import archmage_tower_cards as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.effects import AddCostModifier,ChoiceOption,Damage,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_mana_budget import validate_boundary as validate_budget_boundary
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

RUNE,TOWER=native.LEAVES;P='k650.'
A,B,C,Z,HIGH,OTHER,DISC,LETHAL,UNKNOWN,WATCH,FAIL,RETURN_RUNE,RETURN_TOWER=(P+s for s in
    ('five','seven','three','zero','huge','other','discover','lethal','unknown','watch','fail','return_rune','return_tower'))
CTX=GenerationContext('k650-native-archmage-tower-fixture','experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original Archmage/Tower reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_archmage_tower_cards(r)
    target=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='friendly'if mode=='friendly'else'any')
    for cid,cost,school,hero in ((A,5,SpellSchool.FIRE,CardClass.MAGE),(B,7,SpellSchool.FROST,CardClass.MAGE),
            (C,3,None,CardClass.MAGE),(Z,0,None,CardClass.MAGE),(HIGH,21,None,CardClass.MAGE),
            (OTHER,5,SpellSchool.FIRE,CardClass.ROGUE),(DISC,10,None,CardClass.MAGE),(LETHAL,20,SpellSchool.FIRE,CardClass.MAGE)):
        def body(c,cid=cid):
            if cid==DISC:return (DiscoverFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),source_id=c.source_id),)
            if cid==Z:return ()
            return (Damage(c.target_id,99 if cid==LETHAL else 1,c.source_id,DamageKind.SPELL),)
        r.register_behavior(cid,body);card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,spell_school=school,on_play=cid,
            targeting=None if cid in (Z,DISC)else target,metadata=metadata(hero))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool_card(PoolCard.from_definition(r.card('card.1')))
    members=(A,B,C,HIGH,OTHER,'card.1')if mode=='mixed'else(HIGH,OTHER)if mode=='empty'else(Z,)if mode=='zero'else(LETHAL,)if mode=='lethal'else(A,)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,5,metadata(CardClass.MAGE)));members=(*members,UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards','k650-native-domain',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ValueError('K650 deliberate failure')
    r.register_behavior(FAIL,fail)
    for cid,source in ((RETURN_RUNE,RUNE),(RETURN_TOWER,TOWER)):
        def rescue(c,source=source):
            e=next(e for e in c.state.entities.values()if e.card_id==source and e.zone==Zone.GRAVEYARD)
            return (ReturnSpentSpell(SourceAllocationFact.capture(c.state,e),c.player_id),)
        r.register_behavior(cid,rescue);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        cast=c.state.cast_history[dict(c.event.data)['cast_id']-1]
        is_budget=cast.mana_budget is not None
        caster=c.state.entities.get(cast.caster_id)
        is_tower=caster is not None and caster.card_id==TOWER
        if is_budget and mode=='nested':return (CastSpell(c.player_id,C,c.source_id),)
        if is_budget and mode=='discount':return (AddCostModifier(c.player_id,CostSpec(set_to=0,card_types=(CardType.SPELL,)),c.source_id),)
        if (is_budget and mode=='fail')or(is_tower and mode=='tower_fail'):return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if (is_budget and mode in ('wait_start','wait_finish'))or(is_tower and mode=='tower_wait'):return (prompt(c),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,metadata=metadata(),
        triggers=(TriggerSpec('spell_cast_finished'if mode=='wait_finish'else'spell_cast_started',WATCH),)))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for v in value.values():result.extend(wires(v,name))
    elif isinstance(value,list):
        for v in value:result.extend(wires(v,name))
    return result


class ArchmageTowerTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',hand=(RUNE,),deck=(A,)*12,watch=False,actor=1,hero='mage.hero',rules=None):
        self.mode=mode
        own=PlayerSetup(hero,hand=hand,deck=deck,board=(WATCH,)if watch else(),mana=30,max_mana=30,mana_cap=30)
        other=PlayerSetup('mage.hero',deck=('card.40',)*12,mana=30,max_mana=30,mana_cap=30)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=650,generation_context=CTX),registry(mode),ruleset=rules)

    def budgets(self,g):return [c for c in g.state.cast_history if c.mana_budget is not None]
    def programs(self,g,pid=1):return [e for e in g.state.players[pid].player_effects if e.spec_id==native.PROGRAM]

    def end(self,g,count=1):
        for _ in range(count):g.apply(EndTurn(g.state.active_player))

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_two_original_spells_four_primary_faces_and_no_new_standard_roots(self):
        data=native.load_batch();self.assertEqual(len(data['official_observations']),4)
        self.assertFalse(data['dependencies']or data['new_standard_roots']or data['formal_pool_complete']or data['cn_calibrated'])
        self.assertEqual((registry().card(RUNE).cost,registry().card(TOWER).cost),(9,10))
        self.assertIsNone(registry().card(RUNE).spell_school);self.assertIsNone(registry().card(TOWER).spell_school)

    def test_rune_pays_nine_once_and_four_actual_five_cost_children_spend_twenty(self):
        g=self.game();source=self.play(g,RUNE);casts=self.budgets(g);self.assertEqual(len(casts),4)
        self.assertEqual([c.mana_budget.remaining for c in casts],[20,15,10,5]);self.assertEqual(g.state.players[1].mana,21)
        self.assertTrue(all(c.caster_id==source and c.mana_budget.mage_cast_id==1 and c.mana_budget.school is None for c in casts))
        self.assertEqual([c.mana_budget.previous_cast_id for c in casts],[None,2,3,4]);self.portable(g)

    def test_fixed_mage_domain_includes_multiple_schools_and_ignores_current_warrior_class(self):
        g=self.game(mode='mixed',hero='warrior.hero');self.play(g,RUNE);casts=self.budgets(g)
        self.assertTrue(casts);self.assertTrue({c.card_id for c in casts}<={A,B,C})
        spent=sum(g.registry.pool_card(c.card_id).cost for c in casts);self.assertLessEqual(spent,20);self.assertLess(20-spent,3)

    def test_rune_native_enemy_preference_uses_ordinary_complete_target_receipts(self):
        g=self.game();self.play(g,RUNE)
        self.assertTrue(all(g.state.entities[c.target_id].controller==2 for c in self.budgets(g)))
        self.assertTrue(all(c.target_selection.partition.enemy_ids for c in self.budgets(g)))

    def test_required_friendly_spell_uses_existing_enemy_empty_fallback(self):
        g=self.game(mode='friendly');self.play(g,RUNE)
        self.assertTrue(all(g.state.entities[c.target_id].controller==1 for c in self.budgets(g)))
        self.assertTrue(all(not c.target_selection.partition.enemy_ids for c in self.budgets(g)))

    def test_empty_mage_eligible_domain_does_not_consume_rng_or_create_false_children(self):
        g=self.game(mode='empty');before=g._rng.getstate();self.play(g,RUNE)
        self.assertFalse(self.budgets(g));self.assertEqual(g._rng.getstate(),before)

    def test_unknown_eligible_member_rolls_back_root_before_sampling(self):
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,RUNE)
        self.assertEqual(g.snapshot(),before)

    def test_zero_cost_not_pruned_and_engineering_limit_rolls_back_without_fake_completion(self):
        g=self.game(mode='zero',rules=Ruleset(max_resolution_steps=100));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,RUNE)
        self.assertEqual(g.snapshot(),before)

    def test_local_hand_price_reactions_do_not_replace_printed_budget_costs(self):
        g=self.game(mode='discount',watch=True);self.play(g,RUNE)
        self.assertEqual(len(self.budgets(g)),4);self.assertEqual([c.mana_budget.remaining for c in self.budgets(g)],[20,15,10,5])

    def test_nested_independent_casts_do_not_count_as_budget_picks(self):
        g=self.game(mode='nested',watch=True);self.play(g,RUNE)
        self.assertEqual(len(self.budgets(g)),4);self.assertEqual(len([c for c in g.state.cast_history if c.card_id==C]),4);self.portable(g)

    def test_first_child_start_wait_restores_original_root_and_remaining_budget(self):
        g=self.game(mode='wait_start',watch=True);self.play(g,RUNE);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g)
        while g.state.pending_choice:self.choose(g)
        self.assertEqual(len(self.budgets(g)),4);self.portable(g)

    def test_child_finish_wait_preserves_next_original_pick_and_replays(self):
        g=self.game(mode='wait_finish',watch=True);self.play(g,RUNE);g=self.portable(g)
        while g.state.pending_choice:self.choose(g)
        self.assertEqual(len(self.budgets(g)),4);self.portable(g)

    def test_child_wait_choice_failure_keeps_original_wait_and_rng(self):
        g=self.game(mode='wait_start',watch=True);self.play(g,RUNE);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_child_start_failure_restores_root_payment_allocations_and_rng(self):
        g=self.game(mode='fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,RUNE)
        self.assertEqual(g.snapshot(),before)

    def test_terminal_child_keeps_actual_interrupted_root_and_restores_without_more_budget(self):
        g=self.game(mode='lethal');self.play(g,RUNE);self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(len(self.budgets(g)),1);self.portable(g)

    def test_two_actual_rune_roots_keep_independent_origin_ids_and_payments(self):
        g=self.game(hand=(RUNE,RUNE));self.play(g,RUNE);self.play(g,RUNE)
        self.assertEqual(len(self.budgets(g)),8);self.assertEqual({c.mana_budget.mage_cast_id for c in self.budgets(g)},{1,6})
        self.assertEqual(g.state.players[1].mana,12)

    def test_rehashed_child_cannot_borrow_itself_as_its_original_rune(self):
        g=self.game();self.play(g,RUNE);saved=json.loads(json.dumps(g.snapshot()))
        saved['state']['cast_history'][1]['mana_budget']['mage_cast_id']=2
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('normal','reader'))

    def test_same_physical_recast_cannot_borrow_finished_old_rune_window(self):
        g=self.game(hand=(RUNE,RETURN_RUNE));source=self.play(g,RUNE);self.play(g,RETURN_RUNE);self.play(g,RUNE)
        originals=[c for c in g.state.cast_history if c.card_id==RUNE];self.assertEqual(len(originals),2)
        self.assertEqual([c.source_id for c in originals],[source,source]);tampered=g.clone()
        for i,row in enumerate(tampered._state.cast_history):
            if row.mana_budget is not None and row.mana_budget.mage_cast_id==originals[-1].id:
                tampered._state.cast_history[i]=replace(row,mana_budget=replace(row.mana_budget,mage_cast_id=originals[0].id))
        with self.assertRaisesRegex(ValueError,'already finished'):validate_budget_boundary(tampered)
        saved=json.loads(json.dumps(g.snapshot()))
        for row in saved['state']['cast_history']:
            if row['mana_budget']is not None and row['mana_budget']['mage_cast_id']==originals[-1].id:row['mana_budget']['mage_cast_id']=originals[0].id
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('normal','reader'))

    def test_pending_original_budget_continuation_cannot_be_removed(self):
        g=self.game(mode='wait_start',watch=True);self.play(g,RUNE);saved=json.loads(json.dumps(g.snapshot()))
        def drop(value):
            if isinstance(value,dict):
                for v in value.values():drop(v)
            elif isinstance(value,list):
                value[:]=[v for v in value if not(isinstance(v,dict)and v.get('type','').endswith('.ContinueSpellManaWorth'))]
                for v in value:drop(v)
        drop(saved)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('wait_start','reader'))

    def test_tower_casts_exactly_three_owner_ends_and_expires_after_last_body(self):
        g=self.game(hand=(TOWER,));source=self.play(g,TOWER);self.assertEqual(self.programs(g)[0].remaining_turns,3)
        for i in range(1,6):
            self.end(g);casts=[c for c in g.state.cast_history if c.caster_id==source]
            self.assertEqual(len(casts),(i+1)//2)
        self.assertFalse(self.programs(g));self.portable(g)

    def test_tower_selects_one_physical_deck_spell_and_excludes_all_source_faces(self):
        g=self.game(hand=(TOWER,),deck=(TOWER,A,A,HIGH,'card.1',TOWER));source=self.play(g,TOWER)
        originals={i for i in g.state.players[1].deck if g.state.entities[i].card_id in (A,HIGH)};self.assertEqual(len(originals),3)
        self.end(g);cast=next(c for c in g.state.cast_history if c.caster_id==source)
        self.assertIn(cast.source_id,originals);self.assertEqual(cast.from_zone,Zone.DECK)
        self.assertIsNone(cast.target_selection);self.assertEqual(cast.choices,'random');self.assertEqual(g.state.players[1].mana,20)

    def test_tower_empty_other_spell_domain_preserves_rng_but_consumes_one_clock(self):
        g=self.game(hand=(TOWER,),deck=(TOWER,'card.1'));source=self.play(g,TOWER);before=g._rng.getstate();self.end(g)
        self.assertFalse([c for c in g.state.cast_history if c.caster_id==source]);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(self.programs(g)[0].remaining_turns,2)

    def test_tower_discover_cast_uses_shared_automatic_random_selection(self):
        g=self.game(mode='discover',hand=(TOWER,),deck=(DISC,)+('card.40',)*8);source=self.play(g,TOWER);self.end(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(len([c for c in g.state.cast_history if c.caster_id==source]),1)
        self.assertEqual(self.entity(g,A).zone,Zone.HAND);self.portable(g)

    def test_tower_program_survives_original_spent_source_return_without_rebinding(self):
        g=self.game(hand=(TOWER,RETURN_TOWER));source=self.play(g,TOWER);program=self.programs(g)[0];self.play(g,RETURN_TOWER)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.end(g)
        self.assertEqual(self.programs(g)[0].id,program.id);self.assertEqual(len([c for c in g.state.cast_history if c.caster_id==source]),1)

    def test_tower_child_wait_keeps_original_clock_source_and_deck_tail(self):
        g=self.game(mode='tower_wait',hand=(TOWER,),watch=True);self.play(g,TOWER);self.end(g);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.choose(g);self.assertEqual(self.programs(g)[0].remaining_turns,2);self.portable(g)

    def test_tower_end_failure_restores_clock_physical_spell_and_rng(self):
        g=self.game(mode='tower_fail',hand=(TOWER,),watch=True);self.play(g,TOWER);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_tower_typed_request_requires_original_owner_end_and_program(self):
        g=self.game(hand=(TOWER,));source=self.play(g,TOWER);program=self.programs(g)[0]
        with self.assertRaises(ValueError):CastRandomDeckSpell(1,None,source,player_effect=program)
        self.end(g);end=next(e for e in g.events if e.kind=='turn_ended');program=self.programs(g)[0]
        request=CastRandomDeckSpell(1,None,source,player_effect=program,owner_end=end);request.validate_in_state(g.state,g.registry,g.events)
        for field,value in (('remaining_turns',4),('source_card_id',RUNE)):
            with self.assertRaises(ValueError):replace(request,player_effect=replace(program,**{field:value})).validate_in_state(g.state,g.registry,g.events)
        with self.assertRaises(ValueError):replace(request,owner_end=replace(end,sequence=end.sequence+1)).validate_in_state(g.state,g.registry,g.events)

    def test_two_towers_keep_independent_programs_and_physical_casts(self):
        g=self.game(hand=(TOWER,TOWER));a=self.play(g,TOWER);z=self.play(g,TOWER)
        self.assertEqual(len(self.programs(g)),2);self.end(g)
        self.assertEqual({c.caster_id for c in g.state.cast_history if c.caster_id in (a,z)},{a,z})

    def test_second_owner_tower_has_its_own_deck_sources_and_clock(self):
        g=self.game(hand=(TOWER,),actor=2);source=self.play(g,TOWER,player=2);self.end(g)
        self.assertEqual(self.programs(g,2)[0].remaining_turns,2)
        self.assertTrue(all(c.player_id==2 for c in g.state.cast_history if c.caster_id==source))

    def test_player_views_hide_budget_original_cast_and_typed_deck_requests(self):
        g=self.game(mode='wait_start',watch=True);self.play(g,RUNE)
        for pid in (1,2):
            view=json.dumps(g.for_player(pid).observe())
            for key in ('mage_cast_id','mana_budget','previous_cast_id','CastRandomDeckSpell','resolution_frame','rng_state'):
                self.assertNotIn(key,view)

    def test_real_standard_host_rune_executes_actual_complete_mage_domain(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(RUNE,),deck=('CORE_CS2_182',)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*12)),seed=650,generation_context=f.context),f.registry)
        self.play(g,RUNE);self.assertTrue(self.budgets(g));self.assertTrue(all(c.mana_budget.mage_cast_id==1 for c in self.budgets(g)))

    def test_real_standard_host_tower_casts_original_deck_rune_and_native_budget(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(TOWER,),deck=(RUNE,)+('CORE_CS2_182',)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*12)),seed=651,generation_context=f.context),f.registry)
        source=self.play(g,TOWER);self.end(g);outer=next(c for c in g.state.cast_history if c.card_id==RUNE)
        self.assertEqual((outer.caster_id,outer.from_zone),(source,Zone.DECK));self.assertTrue(self.budgets(g))


if __name__=='__main__':unittest.main()
