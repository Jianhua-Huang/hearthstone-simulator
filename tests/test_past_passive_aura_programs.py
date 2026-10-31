"""Real passive providers, source-independent programs and original cost facts."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_passive_aura_programs as native
from hs_sim.engine import (Attack,CardClass,CastSpell,DeckPolicy,DeckSpec,EndTurn,Game,MatchSetup,PlayCard,PlayerSetup,Scenario,SelectChoice)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChangeManaCrystals,ChoiceOption,Damage,Destroy,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles,Transform)
from hs_sim.engine.costs import (capture_cost_input,capture_generated_quote_fact,capture_quote_fact,quote_unselected_cost)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import (CardAbilityCondition,CardDefinition,CardType,CostAuraSpec,CostSpec,DamageKind,
    Keyword,KeywordAuraSpec,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,DestroyStoredCard,DiscardCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

GLINDA,AVIANA,HALL,WON_HALL,POPGAR,THEO,KAEL,TOPIOR,ELIZA,INZAH=native.ROOTS
WHELP,SLUDGE=native.WHELP,native.SLUDGE
BOLT,MISSILES='CORE_EX1_238','EX1_277'
P='k727.'
A,B,SLEEP,FIRE,FEL,NATURE,ZERO,WEAPON=(P+x for x in('a','b','sleep','fire','fel','nature','zero','weapon'))
KILL,HUSH,RETURN,CONTROL,SHIFT,HURT,AUTO_FEL,EARLY,DISCARD_SLUDGE,DESTROY_SLUDGE,SETUP,PRICES=(P+x for x in
    ('kill','hush','return','control','shift','hurt','auto_fel','early','discard_sludge','destroy_sludge','setup','prices'))
WATCH,FAIL=P+'watch',P+'fail'
CTX=GenerationContext(P+'passive-program-fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=full(role);r=h.registry if host else defaults()
    if not host:
        for cid in(SLUDGE,BOLT,MISSILES):
            card=h.registry.card(cid)
            assert cid not in r.cards
            ids=[getattr(card,k,None)for k in('on_play','battlecry','combo','deathrattle','on_use','on_discard','on_destroyed')]
            ids += [t.behavior_id for t in card.triggers]
            for bid in dict.fromkeys(x for x in ids if x is not None):
                if bid not in r._behaviors:r.register_behavior(bid,h.registry.behavior(bid))
            r.register_card(card);r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_passive_aura_programs(r)
    meta=metadata(collectible=False,tribes=())
    for cid,cost,atk,hp,kw in((A,2,2,8,{}),(B,3,0,20,{}),(SLEEP,1,2,5,dict(dormant_turns=2))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta,**kw));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def stored(c,typ):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SLUDGE)
        return(typ(CardReference.capture(e),c.source_id),)
    def setup(c):
        if any(c.state.entities[i].card_id==THEO for i in c.state.players[c.player_id].board):return()
        return(ChangeManaCrystals(c.player_id,10,filled=True),
            SummonByCard(c.player_id,(SummonEntryMaterial(THEO),),SummonCause.capture(c)),
            AddToHand(c.player_id,SETUP,c.source_id),AddToHand(c.player_id,WATCH,c.source_id),
            AddToHand(c.player_id,A,c.source_id),InvokeBehavior(PRICES,c.source_id,c.player_id))
    def prices(c):return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=6),c.source_id)
        for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SETUP)
    bodies={FIRE:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        FEL:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        NATURE:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),ZERO:lambda c:(GainArmor(c.player_id,1),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),
        CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),),SHIFT:lambda c:(Transform(c.target_id,A),),
        HURT:lambda c:(LoseHealth(c.state.players[c.player_id].hero_id,10,c.source_id),),
        AUTO_FEL:lambda c:(CastSpell(c.player_id,FEL,c.source_id,c.state.players[2].hero_id,targeting='explicit'),),
        EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),DISCARD_SLUDGE:lambda c:stored(c,DiscardCard),
        DESTROY_SLUDGE:lambda c:stored(c,DestroyStoredCard),SETUP:setup,PRICES:prices}
    targeted={FIRE,FEL,NATURE,KILL,HUSH,RETURN,CONTROL,SHIFT,EARLY}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        if cid==PRICES:continue
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=5 if cid in(FIRE,FEL,NATURE)else 0,on_play=cid,
            spell_school={FIRE:SpellSchool.FIRE,FEL:SpellSchool.FEL,NATURE:SpellSchool.NATURE}.get(cid),
            metadata=metadata(tribes=())if cid==SETUP else meta,
            **(dict(targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))if cid in targeted else {})))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=4,attack=1,durability=3,metadata=meta))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K727 deliberate rollback')))
    def wait(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        relevant=(e.kind=='minion_summoned'and target is not None and target.card_id==WHELP or
            e.kind=='player_effect_added'and source is not None and source.card_id in(TOPIOR,ELIZA)or
            e.kind=='health_resolved'and source is not None and source.kind==CardType.SPELL and source.card_id in(FEL,FIRE,NATURE,MISSILES,SLUDGE)or
            e.kind=='minion_summoned'and target is not None and target.card_id==A)
        if not relevant:return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        carriers=[c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in native.ROOTS]
        if carriers:options+=(ChoiceOption('remove','Remove provider',(Destroy(carriers[0].id,c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait);r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,durability=10,metadata=meta,
        triggers=tuple(TriggerSpec(e,WATCH)for e in('minion_summoned','player_effect_added','health_resolved'))))
    r.validate();return r,h.context if host else CTX


class PassiveProgramTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,host=False,watch=False):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=WATCH if watch else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40,armor=500)),
            seed=727,generation_context=ctx),r)
    def opening(self):
        self.mode='small';r=fixture()[0]
        policy=DeckPolicy(P+'opening',P+'opening-target','experimental',tuple(r.cards),max_copies=30)
        decks=tuple(DeckSpec('HERO_08',r.card('HERO_08').initial_hero_power,CardClass.MAGE,(SETUP,)*30)for _ in(1,2))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=727,first_player=1),r)
        while g.state.pending_choice is not None:
            c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,()))
        self.play(g,SETUP);return g
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def quote(self,g,cid,p=1):return quote_unselected_cost(g.state,g.registry,self.entity(g,cid,p)).amount
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def hp(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].health
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,100);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)
    def whelps(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==WHELP]

    def test_complete_thirteen_roles_twenty_six_faces_and_all_ninety_eight_overload_identities(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),26);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['overload_card_ids']),98);self.assertIn(BOLT,d['overload_card_ids'])
        c=fixture()[0].card(WHELP);self.assertEqual((c.attack,c.health,c.cost),(3,3,3));self.assertIn('whelp',c.metadata.subtypes)
        self.assertEqual(c.metadata.tribes,('dragon',));self.assertIn(Keyword.RUSH,c.keywords)
        for cid in native.ROOTS+native.DEPENDENCIES:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_ten_actual_current_host_entries_and_child_effect(self):
        for cid in native.ROOTS:
            g=self.game((cid,),host=True);sid=self.play(g,cid);self.assertTrue(g.state.play_history[0].completed)
            self.assertEqual(g.state.play_history[0].source_id,sid)
            if cid==POPGAR:self.assertEqual(sum(g.state.entities[i].card_id==SLUDGE for i in g.state.players[1].hand),2)
            if cid==TOPIOR:self.assertEqual(g.state.players[1].player_effects[0].spec_id,native.TOPIOR_PROGRAM)
            if cid==INZAH:self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        g=self.game((NATURE,),board=(TOPIOR,));# Board source alone has not installed a Battlecry program.
        self.play(g,NATURE,g.state.players[2].hero_id);self.assertEqual(self.whelps(g),[])

    def test_Glinda_real_minion_play_creates_one_Echo_copy_with_floor_and_turn_expiry(self):
        g=self.game((A,),board=(GLINDA,));self.assertIn(Keyword.ECHO,self.entity(g,A).keywords);self.play(g,A)
        e=self.entity(g,A);self.assertIsNotNone(e.hand_lifetime);self.assertGreaterEqual(self.quote(g,A),1)
        self.play(g,A);self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].hand),1)
        self.end(g);self.assertFalse(any(g.state.entities[i].card_id==A for i in g.state.players[1].hand))

    def test_Glinda_does_not_grant_Echo_to_spells_and_silence_removes_live_contribution(self):
        g=self.game((A,FIRE,HUSH),board=(GLINDA,));self.assertNotIn(Keyword.ECHO,self.entity(g,FIRE).keywords)
        self.play(g,HUSH,self.unit(g,GLINDA).id);self.assertNotIn(Keyword.ECHO,self.entity(g,A).keywords);self.play(g,A)
        self.assertFalse(any(g.state.entities[i].card_id==A for i in g.state.players[1].hand))

    def test_Aviana_zero_is_first_card_of_any_kind_for_each_actual_player_turn(self):
        g=self.game((WEAPON,FIRE,A),board=(AVIANA,),enemy_hand=(FIRE,A))
        self.assertEqual(self.quote(g,WEAPON),0);self.play(g,WEAPON);self.assertEqual(self.quote(g,FIRE),5);self.assertEqual(self.quote(g,A),2)
        self.end(g);self.assertEqual(self.quote(g,FIRE,2),0);self.play(g,FIRE,g.state.players[1].hero_id,2);self.assertEqual(self.quote(g,A,2),2)
        self.end(g);self.assertEqual(self.quote(g,A),0)

    def test_Aviana_source_arrival_does_not_reset_already_played_prefix(self):
        g=self.game((ZERO,AVIANA,A));self.play(g,ZERO);self.play(g,AVIANA);self.assertEqual(self.quote(g,A),2)
        g=self.game((A,),board=(AVIANA,),watch=True);self.play(g,A);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.play_history[-1].cost,0);self.fault(g);g=self.portable(g);self.finish(g);self.portable(g)

    def test_Hallazeal_two_faces_add_spell_damage_and_intrinsic_Lifesteal_once(self):
        for cid in(HALL,WON_HALL):
            g=self.game((HURT,FIRE),board=(cid,));self.play(g,HURT);self.assertEqual(self.hp(g),20)
            self.assertIn(Keyword.LIFESTEAL,self.entity(g,FIRE).keywords);self.play(g,FIRE,g.state.players[2].hero_id)
            self.assertEqual(self.hp(g),23);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,497)

    def test_Hallazeal_split_spell_freezes_one_original_Lifesteal_budget(self):
        g=self.game((HURT,MISSILES),board=(HALL,));self.play(g,HURT);self.play(g,MISSILES)
        self.assertEqual(self.hp(g),24);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,496)

    def test_spell_Lifesteal_automatic_CAST_and_provider_silence_use_same_health_layer(self):
        g=self.game((HURT,AUTO_FEL,HUSH,FIRE),board=(HALL,));self.play(g,HURT);self.play(g,AUTO_FEL)
        self.assertEqual(self.hp(g),23);self.play(g,HUSH,self.unit(g,HALL).id)
        self.assertNotIn(Keyword.LIFESTEAL,self.entity(g,FIRE).keywords);self.play(g,FIRE,g.state.players[2].hero_id);self.assertEqual(self.hp(g),23)

    def test_multiple_spell_providers_union_Lifesteal_without_duplicate_healing(self):
        g=self.game((HURT,FEL),board=(HALL,WON_HALL,POPGAR));self.play(g,HURT);self.play(g,FEL,g.state.players[2].hero_id)
        self.assertEqual(self.hp(g),24);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,496)

    def test_Popgar_only_printed_Fel_discount_and_keyword_and_two_real_Sludges(self):
        g=self.game((POPGAR,FIRE,FEL));self.play(g,POPGAR)
        self.assertEqual(self.quote(g,FEL),3);self.assertEqual(self.quote(g,FIRE),5);self.assertEqual(self.quote(g,SLUDGE),1)
        self.assertIn(Keyword.LIFESTEAL,self.entity(g,SLUDGE).keywords);self.assertNotIn(Keyword.LIFESTEAL,self.entity(g,FIRE).keywords)

    def test_Popgar_Sludge_play_discard_and_destruction_all_use_actual_spell_Lifesteal(self):
        for operation in(SLUDGE,DISCARD_SLUDGE,DESTROY_SLUDGE):
            g=self.game((HURT,SLUDGE,operation)if operation!=SLUDGE else(HURT,SLUDGE),board=(POPGAR,),enemy=(A,));self.play(g,HURT)
            self.play(g,operation);self.assertEqual(self.hp(g),24);self.assertEqual(self.unit(g,A,2).health,4)

    def test_spell_health_wait_independent_restore_RNG_rollback_and_late_provider_removal(self):
        g=self.game((HURT,FEL),board=(POPGAR,),watch=True);self.play(g,HURT);self.play(g,FEL,g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(self.hp(g),22);self.portable(g)

    def test_Kael_every_third_minion_ignores_spells_and_does_not_reset_on_arrival(self):
        g=self.game((A,A,ZERO,A,A),board=(KAEL,));self.play(g,A);self.play(g,ZERO);self.play(g,A)
        self.assertEqual(self.quote(g,A),0);self.play(g,A);self.assertEqual(g.state.play_history[-1].cost,0);self.assertEqual(self.quote(g,A),2)
        g=self.game((A,KAEL,A));self.play(g,A);self.play(g,KAEL);self.assertEqual(self.quote(g,A),0)

    def test_Theo_actual_constructed_physical_membership_distinguishes_same_name_new_copy(self):
        g=self.opening();group=set(g.state.opening.original_entities[0]);hand=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==SETUP]
        original=next(e for e in hand if e.id in group);fresh=next(e for e in hand if e.id not in group)
        for e,amount in((original,6),(fresh,2)):
            fact=capture_quote_fact(g.state,g.registry,capture_cost_input(e));validate_cost_quote_fact(g.registry,fact)
            self.assertEqual(fact.amount,amount);proofs=[c.starting_deck for c in fact.contributions if c.starting_deck is not None]
            if e.id in group:self.assertEqual(proofs,[])
            else:self.assertEqual(proofs[0].source_id,e.id);self.assertTrue(proofs[0].matched)
        g.apply(PlayCard(1,fresh.id));self.assertEqual(g.state.play_history[-1].cost,2)
        g.apply(PlayCard(1,original.id));self.assertEqual(g.state.play_history[-1].cost,6)
        self.portable(g)

    def test_Theo_fresh_generated_quote_and_explicit_unknown_Scenario_are_distinct(self):
        g=self.game(board=(THEO,));fact=capture_generated_quote_fact(g.state,g.registry,1,FIRE,cost=CostSpec(set_to=6))
        self.assertEqual(fact.amount,2);self.assertTrue(any(c.starting_deck is not None and c.starting_deck.source_id is None for c in fact.contributions))
        with self.assertRaises(UnsupportedDefinitionError):
            g=self.game((FIRE,),board=(THEO,));self.quote(g,FIRE)

    def test_Theo_typed_fact_cannot_change_subject_or_borrow_fresh_quote_and_views_hide_it(self):
        g=self.opening();group=set(g.state.opening.original_entities[0]);e=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==SETUP and i not in group)
        fact=capture_quote_fact(g.state,g.registry,capture_cost_input(e))
        c=next(c for c in fact.contributions if c.starting_deck is not None)
        with self.assertRaises(ValueError):replace(fact,contributions=tuple(replace(x,starting_deck=replace(c.starting_deck,source_id=g.state.players[1].hero_id))if x is c else x for x in fact.contributions))
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe());self.assertNotIn('"starting_deck"',view);self.assertNotIn('"original_entities"',view)
        self.portable(g)

    def test_Theo_paid_wait_restores_and_rehashed_original_inventory_clipping_is_rejected(self):
        g=self.opening();self.play(g,WATCH);self.play(g,A)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.play_history[-1].cost,1)
        self.fault(g)
        for player in(0,1):
            saved=g.snapshot();rows=saved['state']['play_history'][-1]['submitted_cost']['quote']['contributions']
            proof=next(c['starting_deck']for c in rows if c['starting_deck']is not None)
            proof['original_entities'][player].pop()
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('reader')[0])
        g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)

    def test_Topior_actual_Nature_CAST_summons_real_Rush_Dragon_after_source_death(self):
        g=self.game((TOPIOR,KILL,NATURE,FIRE),enemy=(A,));sid=self.play(g,TOPIOR);self.play(g,KILL,sid)
        self.play(g,FIRE,g.state.players[2].hero_id);self.assertEqual(self.whelps(g),[])
        self.play(g,NATURE,g.state.players[2].hero_id);self.assertEqual(len(self.whelps(g)),1)
        e=self.whelps(g)[0];self.assertEqual((e.attack,e.health),(3,3));self.assertIn(Keyword.RUSH,e.keywords)
        g.apply(Attack(1,e.id,self.unit(g,A,2).id));self.assertEqual(self.unit(g,A,2).health,5);self.portable(g)

    def test_Topior_old_program_stays_original_player_after_source_control_and_silence(self):
        g=self.game((TOPIOR,CONTROL,NATURE),enemy_hand=(NATURE,HUSH));sid=self.play(g,TOPIOR);self.play(g,CONTROL,sid)
        self.play(g,NATURE,g.state.players[2].hero_id);self.assertEqual(len(self.whelps(g)),1);self.end(g)
        self.play(g,HUSH,sid,2);self.play(g,NATURE,g.state.players[1].hero_id,2);self.assertEqual(self.whelps(g,2),[])

    def test_Topior_repeated_programs_stack_and_full_board_uses_ordinary_capacity(self):
        g=self.game((TOPIOR,TOPIOR,NATURE));self.play(g,TOPIOR);self.play(g,TOPIOR);self.play(g,NATURE,g.state.players[2].hero_id)
        self.assertEqual(len(self.whelps(g)),2)
        g=self.game((TOPIOR,NATURE),board=(A,A,A,A,A,A));self.play(g,TOPIOR);self.play(g,NATURE,g.state.players[2].hero_id)
        self.assertEqual(self.whelps(g),[])

    def test_Topior_real_summon_wait_restores_and_keeps_original_program(self):
        g=self.game((TOPIOR,NATURE),watch=True);self.play(g,TOPIOR);self.finish(g);self.play(g,NATURE,g.state.players[2].hero_id)
        count=0
        while g.state.pending_choice is not None and not self.whelps(g):count+=1;self.assertLess(count,10);self.choose(g)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(len(self.whelps(g)),1);self.portable(g)

    def test_Eliza_actual_and_early_deathrattles_install_permanent_active_board_attack(self):
        g=self.game((EARLY,KILL,A),board=(ELIZA,B));sid=self.unit(g,ELIZA).id;self.play(g,EARLY,sid);self.assertEqual(self.unit(g,B).attack,1)
        self.assertEqual(g.state.death_history,[]);self.play(g,KILL,sid);self.assertEqual(self.unit(g,B).attack,2)
        sid=self.play(g,A);self.assertEqual(g.state.entities[sid].attack,4);self.assertEqual(len(g.state.players[1].player_effects),2)

    def test_Eliza_does_not_buff_hand_or_deck_and_silence_before_death_prevents_program(self):
        g=self.game((KILL,A),board=(ELIZA,),deck=(A,));self.play(g,KILL,self.unit(g,ELIZA).id)
        self.assertEqual(self.entity(g,A).attack,2);self.assertEqual(g.state.entities[g.state.players[1].deck[0]].attack,2)
        g=self.game((HUSH,KILL),board=(ELIZA,B));sid=self.unit(g,ELIZA).id;self.play(g,HUSH,sid);self.play(g,KILL,sid)
        self.assertEqual(self.unit(g,B).attack,0);self.assertEqual(g.state.players[1].player_effects,[])

    def test_Eliza_permanent_program_wait_independent_restore_and_failed_branch(self):
        g=self.game((KILL,),board=(ELIZA,B),watch=True);self.play(g,KILL,self.unit(g,ELIZA).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g)
        self.assertEqual(self.unit(g,B).attack,1);self.portable(g)

    def test_Inzah_complete_Overload_identity_discount_persists_and_stacks_after_source_death(self):
        g=self.game((INZAH,KILL,BOLT,FIRE,INZAH));sid=self.play(g,INZAH);self.assertEqual(self.quote(g,BOLT),0);self.assertEqual(self.quote(g,FIRE),5)
        self.play(g,KILL,sid);self.assertEqual(self.quote(g,BOLT),0);self.play(g,INZAH)
        self.assertEqual(len(g.state.players[1].cost_modifiers),2);self.play(g,BOLT,g.state.players[2].hero_id)
        self.assertEqual(g.state.play_history[-1].cost,0);self.assertEqual(g.state.players[1].overload_owed,1);self.portable(g)

    def test_new_finite_profiles_reject_unrelated_shapes_and_wrong_keyword_school_basis(self):
        with self.assertRaises(ValueError):CostAuraSpec(CostSpec(delta=-1),relation='any_first_card',first_per_turn=True)
        with self.assertRaises(ValueError):CostAuraSpec(CostSpec(delta=-4),relation='friendly_outside_starting_deck')
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.ECHO,'friendly_spells')
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.LIFESTEAL,'friendly_fel_spells',include_self=True)
        with self.assertRaises(ValueError):CardAbilityCondition('fel_spell',basis='current')


if __name__=='__main__':unittest.main()
