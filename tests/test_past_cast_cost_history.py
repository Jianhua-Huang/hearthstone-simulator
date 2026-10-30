"""Real original-cost minion consumers, exact CAST copies and own-turn recasts."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_cast_cost_history as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,Silence)
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CastWhenDrawnSpec,CostSpec,DamageKind,
    Keyword,SpellRepeatSpec,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.registry import Registry
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_source_costs import SpellSourceCostObserverProfile,validate_observer
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

TAMSIN,GAZLOWE,VARGOTH=native.ROOTS
P='k707.';A=P+'plain';M=P+'mech';ALL=P+'all';UNKNOWN=P+'unknown_mech';REPEAT=P+'repeat'
ONE=P+'shadow_one';TWO=P+'shadow_two';ZERO=P+'shadow_zero';FIRE=P+'fire';NONE=P+'no_school';TARGET=P+'target';DRAW_CAST=P+'draw_cast';FILL=P+'fill'
CHEAP=P+'cheap';RAISE=P+'raise';AUTO=P+'auto';OTHER=P+'other';DRAW=P+'draw';HUSH=P+'hush';QUEUE=P+'queue';BAD=P+'bad';PENDING=P+'pending';FAIL=P+'fail'
WAIT_COPY=P+'copy_wait';WAIT_COST=P+'cost_wait';WAIT_HISTORY=P+'history_wait'
HELPERS=(A,M,ALL,REPEAT,ONE,TWO,ZERO,FIRE,NONE,TARGET,DRAW_CAST,FILL,CHEAP,RAISE,AUTO,OTHER,DRAW,HUSH,QUEUE,BAD,PENDING,WAIT_COPY,WAIT_COST,WAIT_HISTORY)
CTX=GenerationContext('k707-explicit-small-fixture','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,tribes in((A,()),(M,('mech',)),(ALL,('all',)),(REPEAT,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=10,
            metadata=replace(meta,collectible=cid in(M,ALL),tribes=tribes),spell_repeats=(SpellRepeatSpec(class_mode='any'),)if cid==REPEAT else()))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,cost,school in((ONE,1,SpellSchool.SHADOW),(TWO,2,SpellSchool.SHADOW),(ZERO,0,SpellSchool.SHADOW),
            (FIRE,1,SpellSchool.FIRE),(NONE,1,None),(TARGET,1,SpellSchool.FIRE),(DRAW_CAST,1,SpellSchool.SHADOW),(FILL,1,SpellSchool.SHADOW)):
        body=((lambda c:(AddToHand(c.player_id,A,c.source_id),))if cid==FILL else
            (lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))if cid==TARGET else(lambda c:(GainArmor(c.player_id,1),)))
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,spell_school=school,metadata=meta,
            requires_target=cid==TARGET,keywords=(Keyword.CASTS_WHEN_DRAWN,)if cid==DRAW_CAST else(),
            cast_when_drawn=CastWhenDrawnSpec()if cid==DRAW_CAST else None))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K707 deliberate original CAST continuation failure')))
    def copy_request(c,cast_id):return CopyCard(None,c.player_id,mode='base',source_id=c.source_id,cost=CostSpec(set_to=0),cast_id=cast_id)
    def failure(c):return ChoiceOption('fault','Fail after RNG',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))
    def queued(c):
        row=next(x for x in c.state.cast_history if x.completed and x.card_id==TWO and x.player_id==c.player_id)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),failure(c)),c.source_id),copy_request(c,row.id))
    def bad(c):
        row=next(x for x in c.state.cast_history if x.completed and x.player_id!=c.player_id)
        return(copy_request(c,row.id),)
    def waiting(c):
        if c.event.kind=='card_created':
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=TAMSIN:return()
        else:
            row=c.state.cast_history[dict(c.event.data)['cast_id']-1]
            if c.event.kind=='spell_cast_started':
                if row.origin!='history':return()
            elif row.card_id not in(ONE,TWO):return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),failure(c),
            ChoiceOption('reprice','Reprice later spells',(AddCostModifier(c.player_id,CostSpec(set_to=0),source_id=c.source_id),))),c.source_id),)
    r.register_behavior(P+'wait',waiting)
    for cid,event in((WAIT_COPY,'card_created'),(WAIT_COST,'spell_cast_finished'),(WAIT_HISTORY,'spell_cast_started')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    bodies={CHEAP:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=0),c.source_id),),
        RAISE:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=2),c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,ONE,c.source_id),),OTHER:lambda c:(CastSpell(3-c.player_id,ONE,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),QUEUE:queued,BAD:bad,
        PENDING:lambda c:(copy_request(c,c.cast.id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            targeting=TargetSpec(zones=(Zone.HAND,Zone.BOARD),kinds=(CardType.MINION,CardType.SPELL))if cid in(CHEAP,RAISE,HUSH)else None))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k707-original-cast-cost-history-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_cast_cost_history(r)
    members=[A,M,ALL]
    if role.startswith('unknown-'):
        r.register_pool_card(PoolCard.from_definition(CardDefinition(UNKNOWN,UNKNOWN,CardType.MINION,cost=2,attack=1,health=1,
            metadata=replace(metadata(collectible=True),tribes=('mech',)))))
        members.append(UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards','explicit-fixture-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members)))
    r.validate();return r


class PastCastCostHistoryTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(('unknown-'if mode=='unknown'else'')+role))

    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*10,watch=None,real_host=False,unknown=False):
        self.mode='host'if real_host else'unknown'if unknown else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*10,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=707,generation_context=h.context if real_host else CTX),
            self.registry_factory(self.mode,'writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_three_faces_and_original_full_source_and_frontier(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['official_observations']),8);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['remaining_frontier_ids']),4)
        for x in d['cards']:self.assertEqual(r.card(x['record']['id']),native.make_definition(x['record']))
        self.assertEqual(asdict(r.spell_source_cost_observers[TAMSIN]),dict(effect_id=TAMSIN,school=SpellSchool.SHADOW))
        self.assertEqual(asdict(r.spell_source_cost_observers[GAZLOWE]),dict(effect_id=GAZLOWE,school=None))

    def test_all_three_actual_paid_hand_entries(self):
        for cid in native.ROOTS:
            g=self.game((cid,));source=self.play(g,cid)
            self.assertEqual(g.state.entities[source].card_id,cid);self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)
            self.assertEqual(len(g.state.play_history),1)

    def test_tamsin_real_shadow_cast_copies_original_face_with_zero_cost_and_lineage(self):
        g=self.game((TAMSIN,ONE));source=self.play(g,TAMSIN);original=self.entity(g,ONE).id;self.play(g,ONE)
        self.assertEqual(self.hand(g),[ONE]);copy=self.entity(g,ONE)
        self.assertNotEqual(copy.id,original);self.assertEqual(copy.origin_entity_id,original);self.assertEqual(copy.cost,0)
        self.assertEqual(g.state.hand_entries[-1].source_id,source);self.assertEqual(len(g.state.cast_history),1);self.assertEqual(self.armor(g),1)
        self.portable(g)

    def test_tamsin_playing_the_zero_copy_does_not_copy_it_again(self):
        g=self.game((ONE,),board=(TAMSIN,));self.play(g,ONE);self.play(g,ONE)
        self.assertEqual(self.hand(g),[]);self.assertEqual([x.source_cost.amount for x in g.state.cast_history],[1,0]);self.assertEqual(self.armor(g),2)

    def test_tamsin_excludes_zero_nonshadow_and_opponent_casts(self):
        for cid in(ZERO,FIRE,NONE):
            g=self.game((cid,),board=(TAMSIN,),enemy_hand=(ONE,));rng=g._rng.getstate();self.play(g,cid)
            self.assertEqual(self.hand(g),[]);self.assertEqual(g._rng.getstate(),rng)
            g.apply(EndTurn(1));self.play(g,ONE,player=2);self.assertNotIn(ONE,self.hand(g))

    def test_tamsin_uses_accepted_current_cost_instead_of_printed_or_later_price(self):
        g=self.game((CHEAP,ONE),board=(TAMSIN,));self.play(g,CHEAP,self.entity(g,ONE).id);self.play(g,ONE)
        self.assertEqual(self.hand(g),[]);self.assertEqual(g.state.cast_history[-1].source_cost.amount,0)
        g=self.game((RAISE,ZERO),board=(TAMSIN,));self.play(g,RAISE,self.entity(g,ZERO).id);self.play(g,ZERO)
        self.assertEqual(self.hand(g),[ZERO]);self.assertEqual(g.state.cast_history[-1].source_cost.amount,2)

    def test_tamsin_ordinary_automatic_cast_uses_cost_without_mana_payment(self):
        g=self.game((AUTO,),board=(TAMSIN,));self.play(g,AUTO)
        self.assertEqual(self.hand(g),[ONE]);row=next(x for x in g.state.cast_history if x.card_id==ONE)
        self.assertEqual((row.origin,row.source_cost.amount),('effect',1));self.assertEqual(g.state.players[1].mana,40);self.portable(g)

    def test_tamsin_native_draw_cast_uses_actual_original_draw_and_replacement(self):
        g=self.game((DRAW,),board=(TAMSIN,),deck=(DRAW_CAST,A));self.play(g,DRAW)
        self.assertIn(DRAW_CAST,self.hand(g));self.assertIn(A,self.hand(g));row=next(x for x in g.state.cast_history if x.card_id==DRAW_CAST)
        self.assertEqual((row.origin,row.source_cost.amount),('draw',1));self.assertEqual(self.armor(g),1);self.portable(g)

    def test_tamsin_each_real_repeat_copies_once_but_does_not_add_a_copy_cast(self):
        g=self.game((ONE,),board=(TAMSIN,REPEAT));self.play(g,ONE)
        self.assertEqual(self.hand(g),[ONE,ONE]);self.assertEqual([x.origin for x in g.state.cast_history],['hand','repeat'])
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,39);self.portable(g)

    def test_tamsin_second_caster_owns_copy_and_private_card_identity(self):
        g=self.game((OTHER,),enemy=(TAMSIN,));self.play(g,OTHER)
        self.assertEqual(self.hand(g),[]);self.assertEqual(self.hand(g,2),[ONE])
        other=[e for e in g.player_events(1)if e['kind']=='card_added_to_hand']
        own=[e for e in g.player_events(2)if e['kind']=='card_added_to_hand']
        self.assertEqual(len(other),1);self.assertIsNone(other[0]['target']['card_id']);self.assertEqual(own[0]['target']['card_id'],ONE);self.portable(g)

    def test_tamsin_silence_removes_the_live_consumer(self):
        g=self.game((HUSH,ONE),board=(TAMSIN,));self.play(g,HUSH,self.unit(g,TAMSIN).id);self.play(g,ONE)
        self.assertEqual(self.hand(g),[])

    def test_tamsin_full_hand_copy_uses_normal_burn_and_no_extra_cast(self):
        g=self.game((FILL,)+(A,)*9,board=(TAMSIN,));self.play(g,FILL)
        self.assertEqual(self.hand(g),[A]*10);self.assertEqual(len(g.state.cast_history),1)
        self.assertTrue(any(e.kind=='card_burned'and g.state.entities[e.target_id].card_id==FILL for e in g.events));self.portable(g)

    def test_tamsin_copy_publication_wait_restores_original_copy_without_duplicate(self):
        g=self.game((ONE,),board=(TAMSIN,),watch=WAIT_COPY);self.play(g,ONE)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.hand(g),[ONE]);self.assertEqual(self.entity(g,ONE).cost,0);self.portable(g)

    def test_original_cost_wait_cannot_reprice_accepted_tamsin_cast(self):
        g=self.game((TWO,),board=(TAMSIN,),watch=WAIT_COST);self.play(g,TWO)
        g=self.portable(g);self.fault(g);self.choose(g,'reprice');self.finish(g)
        self.assertEqual(self.hand(g),[TWO]);self.assertEqual(g.state.cast_history[0].source_cost.amount,2);self.portable(g)

    def test_original_cast_copy_queued_before_choice_restores_and_keeps_exact_identity(self):
        g=self.game((TWO,QUEUE));original=self.entity(g,TWO).id;self.play(g,TWO);self.play(g,QUEUE)
        restored=self.portable(g);self.fault(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hand(g),[TWO]);self.assertEqual(self.entity(g,TWO).origin_entity_id,original)

    def test_cast_copy_rejects_other_players_original_and_unfinished_original_atomically(self):
        g=self.game((OTHER,BAD));self.play(g,OTHER);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),before)
        g=self.game((PENDING,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,PENDING)
        self.assertEqual(g.snapshot(),before)

    def test_original_cast_copy_recipe_rejects_mixed_current_deck_expiry_and_cost_shapes(self):
        base=dict(card=None,player_id=1,mode='base',source_id=3,cost=CostSpec(set_to=0),cast_id=1)
        for patch in(dict(card=CardReference(4,1,Zone.HAND,ONE,0)),dict(mode='current'),dict(destination=Zone.DECK),
                dict(expires_turn=4),dict(source_id=None),dict(cost=None),dict(cost=CostSpec(set_to=1)),dict(cast_id=True),dict(cast_id=0)):
            with self.subTest(patch=patch),self.assertRaises(ValueError):CopyCard(**(base|patch))

    def test_typed_observer_rejects_other_carriers_events_and_school_combinations(self):
        r=fixture()
        for cid,school in((A,None),(VARGOTH,None),(ONE,None),(TAMSIN,SpellSchool.HOLY)):
            with self.subTest(cid=cid,school=school),self.assertRaises(ValueError):validate_observer(r,SpellSourceCostObserverProfile(cid,school))
        for school in(False,'shadow',SpellSchool.FIRE):
            with self.subTest(school=school),self.assertRaises(ValueError):SpellSourceCostObserverProfile(TAMSIN,school)

    def test_gazlowe_qualifies_shadow_fire_and_untyped_one_cost_casts(self):
        for cid in(ONE,FIRE,NONE):
            g=self.game((cid,),board=(GAZLOWE,));self.play(g,cid)
            self.assertEqual(len(self.hand(g)),1);self.assertIn(self.hand(g)[0],(M,ALL));self.assertEqual(g.state.players[1].mana,39)

    def test_gazlowe_original_current_zero_or_two_cost_casts_do_not_generate(self):
        for cid in(ZERO,TWO):
            g=self.game((cid,),board=(GAZLOWE,));rng=g._rng.getstate();self.play(g,cid)
            self.assertEqual(self.hand(g),[]);self.assertEqual(g._rng.getstate(),rng)
        g=self.game((CHEAP,ONE),board=(GAZLOWE,));self.play(g,CHEAP,self.entity(g,ONE).id);self.play(g,ONE);self.assertEqual(self.hand(g),[])

    def test_gazlowe_automatic_cast_qualifies_while_outer_zero_cost_does_not(self):
        g=self.game((AUTO,),board=(GAZLOWE,));self.play(g,AUTO)
        self.assertEqual(len(self.hand(g)),1);self.assertIn(self.hand(g)[0],(M,ALL));self.assertEqual(g.state.players[1].mana,40);self.portable(g)

    def test_gazlowe_uses_full_inventory_and_unknown_mech_is_atomic_failure_not_removed(self):
        g=self.game((ONE,),board=(GAZLOWE,),unknown=True);before=g.snapshot()
        self.assertEqual(len(g.registry.pool('constructed.cards',CTX).members),4)
        with self.assertRaises(ResolutionError):self.play(g,ONE)
        self.assertEqual(g.snapshot(),before);self.assertIn(UNKNOWN,g.registry.pool_cards)

    def test_gazlowe_does_not_observe_opponent_or_silenced_sources(self):
        g=self.game((HUSH,ONE),board=(GAZLOWE,),enemy_hand=(ONE,));self.play(g,HUSH,self.unit(g,GAZLOWE).id);self.play(g,ONE)
        self.assertEqual(self.hand(g),[]);g.apply(EndTurn(1));self.play(g,ONE,player=2);self.assertNotIn(M,self.hand(g));self.assertNotIn(ALL,self.hand(g))

    def test_vargoth_recasts_spell_from_before_its_entry_once_without_hand_payment(self):
        g=self.game((TWO,VARGOTH));self.play(g,TWO);self.play(g,VARGOTH);mana=g.state.players[1].mana;g.apply(EndTurn(1))
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.players[1].mana,mana)
        self.assertEqual([x.origin for x in g.state.cast_history],['hand','history']);self.assertEqual(g.state.cast_history[-1].recast_id,1);self.portable(g)

    def test_vargoth_keeps_duplicate_physical_cast_occurrences_in_history(self):
        g=self.game((ONE,ONE),board=(VARGOTH,));self.play(g,ONE);self.play(g,ONE);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.cast_history),3);self.assertIn(g.state.cast_history[-1].recast_id,(1,2));self.assertEqual(self.armor(g),3)

    def test_vargoth_uses_random_legal_targets_and_actual_history_source(self):
        g=self.game((TARGET,),board=(VARGOTH,A),enemy=(A,));self.play(g,TARGET,g.state.players[2].hero_id);g.apply(EndTurn(1))
        row=g.state.cast_history[-1];self.assertEqual(row.origin,'history');self.assertEqual(row.card_id,TARGET);self.assertIsNotNone(row.target_id)
        self.assertIn(row.target_id,(g.state.players[1].hero_id,g.state.players[2].hero_id,*g.state.players[1].board,*g.state.players[2].board));self.portable(g)

    def test_vargoth_empty_current_turn_and_enemy_turn_neither_recast_nor_sample(self):
        g=self.game(board=(VARGOTH,),enemy_hand=(ONE,));rng=g._rng.getstate();g.apply(EndTurn(1));self.assertEqual(g._rng.getstate(),rng)
        self.play(g,ONE,player=2);g.apply(EndTurn(2));before=len(g.state.cast_history);rng=g._rng.getstate();g.apply(EndTurn(1))
        self.assertEqual(len(g.state.cast_history),before);self.assertEqual(g._rng.getstate(),rng)

    def test_vargoth_silence_prevents_own_end_history_execution(self):
        g=self.game((ONE,HUSH),board=(VARGOTH,));self.play(g,ONE);self.play(g,HUSH,self.unit(g,VARGOTH).id)
        before=len(g.state.cast_history);g.apply(EndTurn(1));self.assertEqual(len(g.state.cast_history),before)

    def test_vargoth_history_cast_wait_restores_and_failure_rolls_back_rng_and_end(self):
        g=self.game((TARGET,),board=(VARGOTH,A),watch=WAIT_HISTORY);self.play(g,TARGET,g.state.players[2].hero_id);g.apply(EndTurn(1))
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_standard_host_real_cost_copy_and_history_entries(self):
        g=self.game((ONE,),board=(TAMSIN,),real_host=True);self.play(g,ONE)
        self.assertEqual(self.hand(g),[ONE]);self.assertEqual(self.entity(g,ONE).cost,0)
        g=self.game((ONE,),board=(VARGOTH,),real_host=True);self.play(g,ONE);g.apply(EndTurn(1));self.assertEqual(self.armor(g),2)
        g=self.game((ONE,),board=(GAZLOWE,),real_host=True)
        candidates=resolve_candidates(g.registry,host().context,'constructed.cards',native.MECHS,current_class=CardClass.MAGE,player_id=1,source_card_id=GAZLOWE)
        self.assertTrue(candidates);self.play(g,ONE);self.assertIn(self.hand(g)[0],{m.card_id for m in candidates})
