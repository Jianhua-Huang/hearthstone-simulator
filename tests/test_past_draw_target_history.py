"""Real paid roots, original physical draws/targets, and complete Legendary entries."""
from dataclasses import asdict, replace
from functools import lru_cache
import json, random, unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_draw_target_history as native
from hs_sim.engine import (CounterSpell, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SetSecret, SnapshotError, UseHeroPower)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    Draw, GainArmor, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.hero_powers import TriggerHeroPower
from hs_sim.engine.model import (BattlecryRepeatSpec, CardDefinition, CardType, CastWhenDrawnSpec,
    CostSpec, DamageKind, Keyword, Rarity, SecretSpec, SpellRepeatSpec, SummonQuantitySpec,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.physical_draw_chains import DrawBattlecryUntilNonDragon, ContinueBattlecryDragonDraws
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    SummonFromPool, resolve_candidates, sample_candidates)
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.spell_target_groups import SpellTargetGroupProfile
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

WRATHION, LAZUL, LIADRIN, PALETRESS = native.ROOTS
P = 'k717.'
A, D, ALL, LEG, Q, REPEAT, CAST_REPEAT = (P+x for x in ('plain','dragon','all','legendary','quantity','repeat','cast_repeat'))
FRAIL = P+'frail'
HIT, NOOP, DRAW, DRAW_CAST, KILL, HUSH, TAKE, CHEAP, AUTO, OTHER, RECAST, DUAL = (
    P+x for x in ('hit','noop','draw','draw_cast','kill','hush','take','cheap','auto','other','recast','dual'))
ARM, SECRET, INDIRECT, ZERO_COPY = (P+x for x in ('arm','secret','indirect','zero_copy'))
WAIT_DRAW, WAIT_COPY, WAIT_SUMMON, FAIL = (P+x for x in ('wait_draw','wait_copy','wait_summon','fail'))
MISSING = P+'missing_legendary'
CTX = GenerationContext(P+'explicit-fixture', 'experimental')


@lru_cache(None)
def legendary_seeds():
    """Arrange a real initial RNG seed; the native producer keeps all members."""
    members=tuple(PoolMember(**x) for x in native.load_batch()['complete_ordinary_legendary_domain']['complete_ordered_members'])
    result={}
    for seed in range(100000):
        cid=sample_candidates(random.Random(seed),members,1,replacement=True)[0]
        result.setdefault(cid,seed)
        if len(result)==len(members):return result
    raise AssertionError('Failed to arrange complete native Legendary seed coverage')


@lru_cache(None)
def fixture(role='writer', real_host=False, mode='normal'):
    h = build_cn37_local_pool_format() if real_host else None
    r = h.registry if h else defaults()
    if not real_host:
        native.register_past_draw_target_history(r)
        if 'CATA_585' not in r.cards:
            from hs_sim.cards.torch_card import register_torch_card
            register_torch_card(r)
    meta = metadata(collectible=False, tribes=())
    r.register_behavior(P+'marker', lambda c:(GainArmor(c.player_id,500),))
    for cid in (A,D,ALL,LEG,Q,REPEAT,CAST_REPEAT,FRAIL):
        extra = dict(metadata=meta)
        if cid in (D,ALL):extra['metadata'] = replace(meta,tribes=('dragon',) if cid==D else ('all',))
        if cid==LEG:extra.update(metadata=replace(meta,collectible=True,rarity=Rarity.LEGENDARY),battlecry=P+'marker')
        if cid==Q:extra['summon_quantities'] = (SummonQuantitySpec(),)
        if cid==REPEAT:extra['battlecry_repeats'] = (BattlecryRepeatSpec(2),)
        if cid==CAST_REPEAT:extra['spell_repeats'] = (SpellRepeatSpec(class_mode='any'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=2 if cid==FRAIL else 30,**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))

    def recast(c):
        old = next(x for x in c.state.cast_history if x.card_id==HIT and x.player_id==c.player_id and x.completed)
        return (RecastSpell(c.player_id,old.id,c.source_id,c.state.players[c.player_id].hero_id,targeting='explicit'),)
    def zero(c):
        old = next(x for x in c.state.cast_history if x.card_id==HIT and x.completed)
        return (CopyCard(None,c.player_id,mode='base',source_id=c.source_id,cost=CostSpec(set_to=0),cast_id=old.id),)
    bodies = {
        HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        NOOP:lambda c:(GainArmor(c.player_id,1),),
        DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        DRAW_CAST:lambda c:(GainArmor(c.player_id,1),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,2),),
        CHEAP:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=0),c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,HIT,c.source_id,c.state.players[c.player_id].hero_id,targeting='explicit'),),
        OTHER:lambda c:(CastSpell(3-c.player_id,HIT,c.source_id,c.state.players[c.player_id].hero_id,targeting='explicit'),),
        RECAST:recast,
        DUAL:lambda c:(),
        ARM:lambda c:(SetSecret(2,SECRET),),
        ZERO_COPY:zero,
        INDIRECT:lambda c:(TriggerHeroPower(c.player_id,c.source_id,
            target_id=c.state.players[3-c.player_id].hero_id,targeting='explicit'),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        targeting = TargetSpec() if cid==HIT else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid in (KILL,HUSH,TAKE,DUAL) else (
            TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,)) if cid==CHEAP else None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2 if cid==HIT else 0,on_play=cid,metadata=meta,
            targeting=targeting,keywords=(Keyword.CASTS_WHEN_DRAWN,) if cid==DRAW_CAST else (),
            cast_when_drawn=CastWhenDrawnSpec() if cid==DRAW_CAST else None))
    r.register_spell_target_group_profile(SpellTargetGroupProfile(DUAL,P+'two-actual-arrows'))
    r.register_secret_condition(P+'counter_condition',lambda c:c.window is not None and
        c.window.kind=='spell' and c.window.player_id!=c.player_id and not c.window.countered)
    r.register_behavior(P+'counter',lambda c:(CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,metadata=meta,keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET,('card_committed',),P+'counter_condition',P+'counter')))

    def fail(c):raise ResolutionError('K717 deliberate accepted choice failure')
    r.register_behavior(FAIL,fail)
    def wait(c):
        target = c.state.entities.get(c.event.target_id)
        if c.source.card_id==WAIT_DRAW and (target is None or target.card_id not in (D,ALL,A,DRAW_CAST)):return ()
        if c.source.card_id==WAIT_COPY and (c.event.source_id is None or
                c.state.entities[c.event.source_id].card_id!=LIADRIN):return ()
        if c.source.card_id==WAIT_SUMMON and (target is None or target.card_id!=LEG):return ()
        options = (ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        if c.source.card_id==WAIT_DRAW:
            options += (ChoiceOption('nested','Make an unrelated reactive draw',(Draw(c.player_id,source_id=c.source_id),)),)
            if c.event.source_id is not None:
                options += (ChoiceOption('kill_source','Kill original source',(Destroy(c.event.source_id,c.source_id),)),
                    ChoiceOption('take_source','Transfer original source',(ChangeControl(c.event.source_id,2),)))
        if c.source.card_id==WAIT_COPY:
            options += (ChoiceOption('new_cast','Cast a new friendly-target spell',(
                CastSpell(c.player_id,HIT,c.source_id,c.state.players[c.player_id].hero_id,targeting='explicit'),)),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    for cid,event in ((WAIT_DRAW,'card_drawn'),(WAIT_COPY,'card_created'),(WAIT_SUMMON,'minion_summoned')):
        r.register_behavior(cid,wait)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=meta,triggers=(TriggerSpec(event,cid),)))

    if not real_host:
        members=[PoolMember(A)] if mode=='empty' else [PoolMember(LEG),PoolMember(A)]
        if mode=='unknown':
            r.register_pool_card(PoolCard.from_definition(CardDefinition(MISSING,MISSING,CardType.MINION,health=2,
                metadata=replace(meta,collectible=True,rarity=Rarity.LEGENDARY))))
            members.append(PoolMember(MISSING))
        r.register_pool(PoolDefinition('constructed.minions','explicit-test-domain',CTX.target_id,CTX.mode,tuple(members)))
    r.validate();return r,h.context if h else CTX


class PastDrawTargetHistoryTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host',mode if mode in ('empty','unknown') else 'normal')[0])
    def game(self,hand=(),*,deck=(),board=(),enemy=(),enemy_hand=(),real_host=False,mode='normal',seed=717):
        self.mode='host' if real_host else mode
        r,context=fixture('writer',real_host,mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,
            mana=40,max_mana=40,mana_cap=40,armor=500,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(A,)*12,board=enemy,mana=40,max_mana=40,
                mana_cap=40,armor=500,hero_power_card_id='HERO_08bp')),seed=seed,generation_context=context),r)
    def hand(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].hand]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def units(self,g,cid,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def power(self,g,p=1):g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,g.state.players[3-p].hero_id))
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,80)
            choices=[x for x in g.legal_actions() if isinstance(x,SelectChoice)];self.assertTrue(choices)
            if any(x.id=='continue' for x in g.state.pending_choice.options):self.choose(g)
            else:g.apply(choices[0])
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def select_card(self,g,cid):
        q=g.state.pending_choice;key=next(x.id for x in q.options if x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def legendary_entry(self,cid):
        g=self.game((PALETRESS,),real_host=True,seed=legendary_seeds()[cid])
        self.play(g,PALETRESS);self.finish(g)
        self.assertTrue(any(e.card_id==cid for e in g.state.entities.values()))
        self.assertEqual(len(g.state.battlecry_history),1)
        return g

    def test_complete_four_faces_and_full_past_and_178_ordinary_domain(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),10)
        self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['complete_ordinary_legendary_domain']['members']),178)
        self.assertFalse(d['complete_past_source_bound']);self.assertNotIn('MIS_701',fixture()[0].cards)

    def test_Wrathion_draws_original_top_order_including_final_non_Dragon(self):
        g=self.game((WRATHION,),deck=(D,D,A,D));ids=tuple(g.state.players[1].deck);rng=g.snapshot()['rng_state']
        source=self.play(g,WRATHION)
        self.assertEqual(tuple(g.state.players[1].hand),ids[:3]);self.assertEqual(g.state.players[1].deck,list(ids[3:]))
        self.assertEqual([r.source_id for r in g.state.draw_history],[source]*3)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertEqual(g.state.players[1].mana,34)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_Wrathion_first_non_Dragon_is_still_drawn_once(self):
        g=self.game((WRATHION,),deck=(NOOP,D));self.play(g,WRATHION)
        self.assertEqual(self.hand(g),[NOOP]);self.assertEqual(len(g.state.draw_history),1)

    def test_Wrathion_All_tribe_continues_as_a_Dragon(self):
        g=self.game((WRATHION,),deck=(ALL,D,A));self.play(g,WRATHION)
        self.assertEqual(self.hand(g),[ALL,D,A]);self.assertEqual(len(g.state.draw_history),3)

    def test_Wrathion_burned_Dragons_continue_and_burned_non_Dragon_stops(self):
        g=self.game((WRATHION,)+(NOOP,)*9,deck=(D,D,D,A,D));self.play(g,WRATHION)
        self.assertEqual([r.outcome for r in g.state.draw_history],['hand','burned','burned','burned'])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[D])

    def test_Wrathion_after_last_Dragon_makes_one_fatigue_attempt(self):
        for deck,expected in (((),['fatigue']),((D,),['hand','fatigue'])):
            g=self.game((WRATHION,),deck=deck);self.play(g,WRATHION)
            self.assertEqual([r.outcome for r in g.state.draw_history],expected)

    def test_Wrathion_original_draw_spell_stops_after_its_replacement_chain(self):
        g=self.game((WRATHION,),deck=(DRAW_CAST,D,A,D));self.play(g,WRATHION)
        self.assertEqual([r.card_id for r in g.state.draw_history],[DRAW_CAST,D])
        self.assertEqual(g.state.draw_history[1].parent_id,1);self.assertEqual(self.hand(g),[D]);self.portable(g)

    def test_Wrathion_wait_restores_original_tail_and_failure_rolls_back_RNG(self):
        g=self.game((WRATHION,),deck=(D,A,D),board=(WAIT_DRAW,));source=self.play(g,WRATHION)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g)
        self.choose(g,'kill_source');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hand(g),[D,A])

    def test_Wrathion_reactive_draw_cannot_replace_the_controlling_direct_draw(self):
        g=self.game((WRATHION,),deck=(D,A,D,NOOP,D),board=(WAIT_DRAW,));self.play(g,WRATHION)
        self.choose(g,'nested');self.finish(g)
        self.assertEqual(self.hand(g),[D,A,D,NOOP]);self.assertEqual(len(g.state.draw_history),4)

    def test_Wrathion_accepted_recipient_survives_source_control_change(self):
        g=self.game((WRATHION,),deck=(D,A),board=(WAIT_DRAW,));source=self.play(g,WRATHION)
        self.choose(g,'take_source');self.finish(g)
        self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(self.hand(g),[D,A])

    def test_real_Wrathion_Battlecry_repeat_draws_fresh_sequence_and_pays_once(self):
        g=self.game((WRATHION,),deck=(D,A,D,A,D),board=(REPEAT,));self.play(g,WRATHION)
        self.assertEqual(self.hand(g),[D,A,D,A]);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(g.state.players[1].mana,34)

    def test_successive_draw_receipts_reject_foreign_and_unfinished_prefixes(self):
        g=self.game((WRATHION,),deck=(D,A),board=(WAIT_DRAW,));self.play(g,WRATHION)
        request=DrawBattlecryUntilNonDragon(g.state.battlecry_history[-1].id)
        tail=ContinueBattlecryDragonDraws(request,(g.state.draw_history[-1].id,));tail.validate_in_state(g.state,g.registry)
        with self.assertRaises(ValueError):ContinueBattlecryDragonDraws(request,(1,1))
        with self.assertRaises(ValueError):ContinueBattlecryDragonDraws(request,(2,)).validate_in_state(g.state,g.registry)
        self.finish(g)
        with self.assertRaises(ValueError):tail.validate_in_state(g.state,g.registry)

    def test_Lazul_distinct_offers_are_private_and_do_not_move_original_hand(self):
        g=self.game((LAZUL,),enemy_hand=(A,D,NOOP,HIT,ALL));original=tuple(g.state.players[2].hand)
        self.play(g,LAZUL);q=g.state.pending_choice;self.assertEqual(len(q.options),3)
        self.assertEqual(len({x.card_id for x in q.options}),3);offered={x.card_id for x in q.options}
        mine=json.dumps(g.for_player(1).observe());other=json.dumps(g.for_player(2).observe())
        for cid in set((A,D,NOOP,HIT,ALL))-offered:self.assertNotIn(cid,mine)
        self.assertNotIn('zone-1',other);self.assertEqual(tuple(g.state.players[2].hand),original)
        g=self.portable(g);self.finish(g);self.assertEqual(len(self.hand(g)),1)
        self.assertEqual(tuple(g.state.players[2].hand),original);self.assertEqual(len(g.state.card_discovery_history),1)

    def test_Lazul_duplicate_physical_cards_offer_one_base_face(self):
        g=self.game((LAZUL,),enemy_hand=(A,A,A));self.play(g,LAZUL)
        self.assertEqual([x.card_id for x in g.state.pending_choice.options],[A]);self.select_card(g,A)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.players[2].hand),3)

    def test_Lazul_empty_hand_is_no_choice_and_no_RNG(self):
        g=self.game((LAZUL,));rng=g.snapshot()['rng_state'];self.play(g,LAZUL)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_Lazul_invalid_choice_restores_same_offer_and_private_history(self):
        g=self.game((LAZUL,),enemy_hand=(D,A));self.play(g,LAZUL);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'nonexistent')
        self.assertEqual(g.snapshot(),saved);g=self.portable(g);self.select_card(g,D)
        self.assertEqual(self.hand(g),[D]);self.portable(g)

    def test_Lazul_repeated_discoveries_use_ordinary_hand_overflow(self):
        g=self.game((LAZUL,)+(NOOP,)*9,board=(REPEAT,),enemy_hand=(A,));self.play(g,LAZUL);self.finish(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(self.hand(g).count(A),1)
        self.assertEqual(len(g.state.card_discovery_history),2);self.assertEqual(g.state.players[1].mana,37)

    def test_Liadrin_uses_original_friendly_character_facts_after_death_or_control(self):
        g=self.game((HIT,HIT,HIT,TAKE,KILL,LIADRIN),board=(A,),enemy=(D,))
        own=self.unit(g,A).id;foe=self.unit(g,D,2).id
        self.play(g,HIT,own);self.play(g,HIT,g.state.players[1].hero_id);self.play(g,HIT,foe)
        self.play(g,TAKE,own);self.play(g,KILL,own);self.play(g,LIADRIN)
        self.assertEqual(self.hand(g),[HIT,HIT,TAKE]);self.assertEqual(g.state.players[1].mana,27)
        self.portable(g)

    def test_Liadrin_excludes_untargeted_opponent_and_countered_attempts(self):
        g=self.game((NOOP,OTHER,ARM,HIT,LIADRIN));self.play(g,NOOP);self.play(g,OTHER);self.play(g,ARM)
        self.play(g,HIT,g.state.players[1].hero_id);self.assertEqual(g.state.cast_history[-1].failure,'countered')
        self.play(g,LIADRIN);self.assertEqual(self.hand(g),[])

    def test_Liadrin_counts_actual_hand_repeat_effect_and_history_CASTs(self):
        g=self.game((HIT,AUTO,RECAST,LIADRIN),board=(CAST_REPEAT,));self.play(g,HIT,g.state.players[1].hero_id)
        self.play(g,AUTO);self.play(g,RECAST);expected=[x for x in g.state.cast_history if x.card_id==HIT]
        self.assertTrue({'hand','repeat','effect','history'}<={x.origin for x in expected})
        self.play(g,LIADRIN);self.assertEqual(self.hand(g),[HIT]*len(expected));self.portable(g)

    def test_Liadrin_secondary_friendly_arrow_counts_each_CAST_once(self):
        for friendly_primary in (False,True):
            g=self.game((DUAL,LIADRIN),board=(A,D),enemy=(A,));own=self.unit(g,A).id
            first=self.unit(g,D).id if friendly_primary else self.unit(g,A,2).id
            spell=self.entity(g,DUAL).id;g.apply(PlayCard(1,spell,first,target_ids=(first,own)))
            self.play(g,LIADRIN);self.assertEqual(self.hand(g),[DUAL]);self.portable(g)

    def test_Liadrin_resets_old_hand_cost_and_retains_prior_zero_copy_recipe(self):
        g=self.game((CHEAP,HIT,ZERO_COPY,LIADRIN));original=self.entity(g,HIT).id
        self.play(g,CHEAP,original);self.play(g,HIT,g.state.players[1].hero_id);self.play(g,ZERO_COPY)
        self.assertEqual(g.state.entities[self.entity(g,HIT).id].cost,0)
        self.play(g,LIADRIN);copies=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==HIT]
        self.assertEqual([e.cost for e in copies],[0,2])

    def test_Liadrin_freezes_original_order_and_restores_remaining_copies(self):
        g=self.game((HIT,HIT,LIADRIN),board=(WAIT_COPY,));self.play(g,HIT,g.state.players[1].hero_id)
        self.play(g,HIT,g.state.players[1].hero_id);self.play(g,LIADRIN);self.fault(g);g=self.portable(g)
        self.choose(g,'new_cast');self.finish(g)
        self.assertEqual(self.hand(g),[HIT,HIT]);self.assertEqual(sum(x.card_id==HIT for x in g.state.cast_history),3)
        self.portable(g)

    def test_Liadrin_original_generated_recipe_is_not_later_physical_spell_value(self):
        from hs_sim.engine.native_spell_values import bound_value
        g=self.game((HIT,HIT,'CATA_585',LIADRIN),board=(FRAIL,FRAIL));first,second=g.state.players[1].board
        self.play(g,HIT,first);original=self.play(g,'CATA_585',first)
        self.play(g,HIT,second);self.play(g,'CATA_585',second);self.play(g,LIADRIN)
        spells=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='CATA_585']
        self.assertEqual(bound_value(g.state.entities[original]).amount,6)
        self.assertCountEqual([None if bound_value(e) is None else bound_value(e).amount for e in spells],[None,6,7])
        self.portable(g)

    def test_original_CAST_copy_allows_only_ordinary_or_prior_zero_cost_base_shape(self):
        CopyCard(None,1,mode='base',source_id=1,cast_id=1)
        CopyCard(None,1,mode='base',source_id=1,cast_id=1,cost=CostSpec(set_to=0))
        for change in (dict(cost=CostSpec(delta=-1)),dict(mode='current'),dict(destination=Zone.DECK),dict(expires_turn=1)):
            fields=dict(mode='base',source_id=1,cast_id=1);fields.update(change)
            with self.assertRaises(ValueError):CopyCard(None,1,**fields)

    def test_Paletress_current_Battlecry_and_real_manual_Inspire_both_summon(self):
        g=self.game((PALETRESS,));self.play(g,PALETRESS);self.assertEqual(len(self.units(g,LEG)),1)
        armor=g.state.entities[g.state.players[1].hero_id].armor;self.power(g)
        self.assertEqual(len(self.units(g,LEG)),2);self.assertEqual(g.state.players[1].mana,31)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,armor)
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_Paletress_opponent_and_indirect_powers_do_not_trigger_Inspire(self):
        g=self.game((PALETRESS,INDIRECT));self.play(g,PALETRESS);self.play(g,INDIRECT)
        self.assertEqual(len(self.units(g,LEG)),1);g.apply(EndTurn(1));self.power(g,2)
        self.assertEqual(len(self.units(g,LEG)),1)

    def test_Paletress_silence_removes_actual_Inspire(self):
        g=self.game((PALETRESS,HUSH));source=self.play(g,PALETRESS);self.play(g,HUSH,source);self.power(g)
        self.assertEqual(len(self.units(g,LEG)),1)

    def test_Paletress_quantity_capacity_and_empty_pool_use_shared_rules(self):
        g=self.game((PALETRESS,),board=(Q,));self.play(g,PALETRESS);self.assertEqual(len(self.units(g,LEG)),2)
        g=self.game((PALETRESS,),board=(A,)*6);rng=g.snapshot()['rng_state'];self.play(g,PALETRESS)
        self.assertEqual(len(self.units(g,LEG)),0);self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((PALETRESS,),mode='empty');rng=g.snapshot()['rng_state'];self.play(g,PALETRESS)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(len(g.state.players[1].board),1)

    def test_Paletress_unknown_eligible_entry_rejects_full_paid_action(self):
        g=self.game((PALETRESS,),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,PALETRESS)
        self.assertEqual(g.snapshot(),before)

    def test_Paletress_real_summon_wait_restores_and_failed_choice_is_atomic(self):
        g=self.game((PALETRESS,),board=(WAIT_SUMMON,));self.play(g,PALETRESS);self.fault(g);g=self.portable(g)
        self.finish(g);self.power(g);self.finish(g);self.assertEqual(len(self.units(g,LEG)),2)

    def test_actual_host_preserves_complete_178_member_order_and_weights(self):
        r,context=fixture(real_host=True);rows=resolve_candidates(r,context,'constructed.minions',native.LEGENDARIES)
        self.assertEqual([asdict(x) for x in rows],native.load_batch()['complete_ordinary_legendary_domain']['complete_ordered_members'])

    def test_every_actual_host_Legendary_has_original_Paletress_attributed_pool_entry(self):
        for row in native.load_batch()['complete_ordinary_legendary_domain']['members']:
            cid=row['card_id']
            with self.subTest(card=cid):
                self.legendary_entry(cid)

    def test_actual_host_Colossal_generated_dependencies_and_dormant_entry(self):
        from hs_sim.engine.model import PaymentType
        for cid in ('CATA_154','CATA_155','TIME_063'):
            g=self.legendary_entry(cid)
            if cid=='TIME_063':self.assertIsNotNone(self.unit(g,cid).dormancy)
            else:
                self.assertEqual(len(g.state.players[1].board),4)
                self.assertEqual(len(g.state.players[1].hand),2)
                for eid in g.state.players[1].hand:
                    card=g.state.entities[eid];definition=g.registry.card(card.card_id)
                    if cid=='CATA_154':
                        self.assertEqual(card.kind,CardType.SPELL)
                        self.assertNotIn(g.state.players[1].hero_class,definition.metadata.classes)
                        self.assertEqual(card.cost,max(0,definition.cost-1))
                    else:
                        self.assertEqual((card.kind,definition.cost),(CardType.MINION,2))
                        self.assertTrue(any(x.payment==PaymentType.HEALTH and
                            x.expires_turn==g.state.turn for x in card.enchantments))
            self.portable(g)

    def test_actual_host_all_four_paid_roots_use_their_real_paths(self):
        g=self.game((WRATHION,),deck=(D,A),real_host=True);self.play(g,WRATHION);self.assertEqual(self.hand(g),[D,A])
        g=self.game((LAZUL,),enemy_hand=(A,),real_host=True);self.play(g,LAZUL);g=self.portable(g);self.finish(g)
        self.assertEqual(self.hand(g),[A])
        g=self.game((HIT,LIADRIN),real_host=True);self.play(g,HIT,g.state.players[1].hero_id);self.play(g,LIADRIN)
        self.assertEqual(self.hand(g),[HIT])
        g=self.game((PALETRESS,),real_host=True);self.play(g,PALETRESS);self.finish(g);self.power(g);self.finish(g)
        self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)

    def test_old_future_or_boolean_snapshot_schema_is_rejected(self):
        g=self.game((WRATHION,));saved=g.snapshot()
        for version in (662,664,True):
            bad=dict(saved,schema_version=version)
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,g.registry)
