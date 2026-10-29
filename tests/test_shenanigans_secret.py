"""Real Shenanigans, original draw cancellation and actual physical beneficiaries."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import shenanigans_secret as native
from hs_sim.cards.conditional_cards import SCRIPTS
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_deathrattle_memory_cards import register_native_deathrattle_memory_cards
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.draw_beneficiaries import DrawMatchingWithFollowup
from hs_sim.engine.draw_transformations import TransformDrawnCard,EVENT,KEY,validate_transformation
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,CastWhenDrawnSpec,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup,DrawGroupSlot,DrawGroupReward
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_sequences import DrawWithCostReduction,DrawWithTemporaryCostReduction,DrawMatchingWithCostReduction
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard,ReorderZone
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CARD=native.CARD;BANANA=native.BANANA;PLAT='TLC_603';P='k646.'
A,B,CWD,SPELL,WATCH=(P+x for x in ('plain','other','cwd','spell','watch'))
DRAW,DISCOUNT,TEMP,MATCH,GCOST,GBUFF,GSET,GDISCARD,FOLLOW,GRANT,TOP,KILL,FILLDRAW,CYCLE,FAIL=(P+x for x in
    ('draw','discount','temp','match','group_cost','group_buff','group_set','group_discard','follow','grant','top','kill','fill_draw','cycle','fail'))
MINIONS=PoolQuery(kinds=(CardType.MINION,))


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('extra','Extra draw',(
        Draw(2,1,c.source_id),)),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[1].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original K646 reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();raw=native.load_batch()['existing_dependencies'][0]['record']
    r.register_behavior('cards.conditions.banana_buff',lambda c:SCRIPTS['banana_buff'](c,r))
    r.register_card(CardDefinition(BANANA,raw['name'],CardType.SPELL,cost=1,on_play='cards.conditions.banana_buff',
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=metadata_from_record(raw)))
    native.register_shenanigans_secret(r);register_native_deathrattle_memory_cards(r)
    for cid,cost in ((A,5),(B,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=3,health=6,metadata=metadata(tribes=())))
    r.register_behavior(SPELL,lambda c:(GainArmor(c.player_id,7),))
    r.register_behavior(CWD+'.after',lambda c:(GainArmor(c.player_id,11),))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=3,on_play=SPELL,metadata=metadata()))
    r.register_card(CardDefinition(CWD,CWD,CardType.SPELL,cost=3,on_play=SPELL,keywords=(Keyword.CASTS_WHEN_DRAWN,),
        cast_when_drawn=CastWhenDrawnSpec(after_draw=CWD+'.after'),metadata=metadata()))
    def fail(c):raise ValueError('K646 deliberate late failure')
    r.register_behavior(FAIL,fail)
    def group(c,kind):
        query=MINIONS if kind in ('buff_all','set_stats_cost_all') else None
        return (DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(query),)*(3 if kind=='discard_drawn_spells'else 1),
            DrawGroupReward(kind,2 if query else 1 if kind=='cost_all'else 0)),)
    def grant(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==SPELL)
        material=CapturedCardCopyMaterial.capture(c.state,target)
        return shuffled(c,(CopyCard(material,c.player_id,Zone.DECK,source_id=c.source_id,cast_when_drawn=True),))
    def order_top(c):
        deck=c.state.players[c.player_id].deck
        target=next(i for i in deck if any(a.draw_cast is not None for a in c.state.entities[i].abilities))
        return (ReorderZone(c.player_id,Zone.DECK,(target,*(i for i in deck if i!=target))),)
    def cycle(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==BANANA)
        return (MoveCard(CardReference.capture(target),c.player_id,Zone.DECK,position='top',source_id=c.source_id),Draw(c.player_id,1,c.source_id))
    r.register_behavior(FOLLOW+'.reward',lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,2,c.source_id),))
    scripts={DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),DISCOUNT:lambda c:(DrawWithCostReduction(c.player_id,1,c.source_id),),
        TEMP:lambda c:(DrawWithTemporaryCostReduction(c.player_id,1,c.source_id,c.state.turn),),
        MATCH:lambda c:(DrawMatchingWithCostReduction(c.player_id,1,c.source_id,MINIONS),),
        FOLLOW:lambda c:(DrawMatchingWithFollowup(c.player_id,MINIONS,c.source_id,FOLLOW+'.reward'),),
        GCOST:lambda c:group(c,'cost_all'),GBUFF:lambda c:group(c,'buff_all'),GSET:lambda c:group(c,'set_stats_cost_all'),
        GDISCARD:lambda c:group(c,'discard_drawn_spells'),GRANT:grant,TOP:order_top,KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        FILLDRAW:lambda c:(*(AddToHand(c.player_id,A,c.source_id)for _ in range(10)),Draw(c.player_id,1,c.source_id)),CYCLE:cycle}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid==KILL,metadata=metadata()))
    def watch(c):
        e=c.event;target=c.state.entities.get(e.target_id);source=c.state.entities.get(e.source_id)
        revealed=e.kind=='secret_revealed'and source is not None and source.card_id==CARD
        transformed=e.kind=='stored_card_transformed'and target is not None and target.card_id==BANANA
        entered=e.kind=='hand_card_entered'and target is not None and target.card_id==BANANA
        second=e.kind=='card_drawn'and e.player_id==2 and len([d for d in c.state.draw_history if d.player_id==2 and d.outcome in('hand','cast')])==2
        if mode=='fill'and revealed:return tuple(AddToHand(2,A,c.source_id)for _ in range(10))
        if mode=='depart'and revealed:
            row=c.state.draw_history[-1]
            return (MoveCard(CardReference.capture(c.state.entities[row.entity_id]),2,Zone.DECK,position='top',source_id=c.source_id),)
        if mode=='root_fail'and transformed:return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if ((mode=='reveal_wait'and revealed)or(mode=='transform_wait'and transformed)or
                (mode=='hand_wait'and entered)or(mode=='draw_wait'and second)):
            return (prompt(c),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(e,WATCH)for e in('secret_revealed','stored_card_transformed','hand_card_entered','card_drawn'))))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


def wires(value,name):
    if isinstance(value,dict):
        result=[value]if str(value.get('type','')).endswith('.'+name)else[]
        return result+[x for v in value.values()for x in wires(v,name)]
    if isinstance(value,list):return [x for v in value for x in wires(v,name)]
    return []


class ShenanigansSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',deck=(A,A,B),hand=(DRAW,),watch=False):
        self.mode=mode
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(CARD,),deck=(A,)*5,mana=10,max_mana=10),
            PlayerSetup('mage.hero',hand=hand,board=((WATCH,A)if watch else(A,)),deck=deck,mana=10,max_mana=10)),seed=646),registry(mode))
        self.play(g,CARD);g.apply(EndTurn(1));return g

    def trigger(self,g,card=DRAW):return self.play(g,card,player=2)

    def row(self,g):return next(d for d in g.state.draw_history if d.transformation is not None)

    def finish(self,g):
        while g.state.pending_choice:self.choose(g)

    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        return saved

    def test_complete_original_records_and_unchanged_real_banana_definition(self):
        d=native.load_batch();self.assertEqual([x['record']['id']for x in d['dependencies']],[CARD])
        self.assertEqual([x['record']['id']for x in d['existing_dependencies']],[BANANA])
        self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(canonical_digest(asdict(registry().card(BANANA))),native.BANANA_HASH)
        self.assertFalse(d['source_scope_bound']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_first_draw_keeps_secret_second_draw_transforms_same_physical_body(self):
        g=self.game();self.assertEqual(len(g.state.players[1].secrets),1)
        target=g.state.players[2].deck[0];self.trigger(g)
        row=self.row(g);self.assertEqual((row.entity_id,row.card_id,row.outcome,row.phase),(target,A,'hand','done'))
        self.assertEqual((g.state.entities[target].card_id,g.state.entities[target].zone),(BANANA,Zone.HAND))
        self.assertEqual(row.hand_entry_id,row.transformation.hand_entry_id)
        self.assertEqual(len(g.state.draw_history),2);self.assertFalse(g.state.players[1].secrets);self.portable(g)

    def test_generated_banana_is_actual_targeted_plus_one_plus_one_spell(self):
        g=self.game();target=self.entity(g,A,2,'board').id;self.trigger(g)
        self.play(g,BANANA,target,player=2)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,7))

    def test_native_draw_cast_cancels_cast_replacement_and_native_after_draw(self):
        g=self.game(deck=(A,CWD,B));target=g.state.players[2].deck[0];self.trigger(g)
        row=self.row(g);self.assertEqual((row.entity_id,row.card_id,row.outcome),(target,CWD,'cast'))
        self.assertIsNone(row.cast_id);self.assertIsNone(row.replacement_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].deck],[B])
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn']),2)
        self.assertEqual(len([h for h in g.state.hand_entries if h.entity_id==target]),1)
        self.portable(g)

    def test_first_draw_cast_replacement_is_actual_second_draw(self):
        g=self.game(deck=(CWD,A,B));row=self.row(g)
        self.assertEqual((row.card_id,row.parent_id,row.outcome),(A,1,'hand'))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,18)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_granted_draw_cast_keeps_original_basis_but_does_not_cast_or_replace(self):
        g=self.game(deck=(A,SPELL,B),hand=(GRANT,TOP,DRAW))
        self.trigger(g,GRANT);self.trigger(g,TOP);target=g.state.players[2].deck[0];self.trigger(g)
        row=self.row(g);self.assertEqual((row.entity_id,row.card_id,row.outcome),(target,SPELL,'cast'))
        self.assertIsNotNone(row.cast_grant);self.assertIsNone(row.cast_id);self.assertIsNone(row.replacement_id)
        self.assertFalse(any(a.draw_cast is not None for a in g.state.entities[target].abilities))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0);self.portable(g)

    def test_draw_and_temporary_discounts_follow_actual_banana_result(self):
        for card in(DISCOUNT,TEMP,GCOST):
            for face in(A,CWD):
                with self.subTest(card=card,face=face):
                    g=self.game(deck=(A,face,B),hand=(card,));self.trigger(g,card);eid=self.row(g).entity_id
                    self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,0)
                    if card==TEMP:
                        g.apply(EndTurn(2));self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,1)

    def test_matching_discount_and_minion_only_followups_use_actual_type(self):
        for card in(MATCH,FOLLOW,GBUFF,GSET):
            with self.subTest(card=card):
                g=self.game(deck=(A,A),hand=(card,));self.trigger(g,card);eid=self.row(g).entity_id
                self.assertEqual(g.state.entities[eid].card_id,BANANA)
                self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,0 if card==MATCH else 2 if card==GSET else 1)
                self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(0,0))

    def test_group_discard_recognizes_actual_transformed_spell(self):
        g=self.game(hand=(GDISCARD,));self.trigger(g,GDISCARD);row=self.row(g)
        self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.discard_history[-1].card.card_id,BANANA);self.portable(g)

    def test_native_deathrattle_remembers_original_normal_and_converted_draw(self):
        for face in(A,CWD):
            with self.subTest(face=face):
                g=self.game(deck=(A,face,B),hand=(PLAT,KILL));source=self.trigger(g,PLAT);row=self.row(g)
                memory=next(a.deathrattle_memory for a in g.state.entities[source].abilities if a.deathrattle_memory is not None)
                self.assertEqual([(x.draw_id,x.entity_id,x.hand_entry_id)for x in memory.draws],[(row.id,row.entity_id,row.hand_entry_id)])
                self.play(g,KILL,source,player=2);self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD);self.portable(g)

    def test_converted_draw_grant_and_native_observer_coexist(self):
        g=self.game(deck=(A,SPELL,B),hand=(GRANT,TOP,PLAT,KILL));self.trigger(g,GRANT);self.trigger(g,TOP)
        source=self.trigger(g,PLAT);row=self.row(g);self.assertIsNotNone(row.cast_grant);self.assertIsNotNone(row.observer)
        self.play(g,KILL,source,player=2);self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD);self.portable(g)

    def test_native_memory_does_not_follow_later_reacquisition_of_same_banana(self):
        g=self.game(deck=(A,CWD,B),hand=(PLAT,CYCLE,KILL));source=self.trigger(g,PLAT);row=self.row(g)
        self.trigger(g,CYCLE);self.assertGreater(g.state.entities[row.entity_id].hand_entry_id,row.hand_entry_id)
        self.play(g,KILL,source,player=2);self.assertEqual(g.state.entities[row.entity_id].zone,Zone.HAND)

    def test_full_hand_at_acceptance_burns_without_triggering_secret(self):
        g=self.game(hand=(FILLDRAW,));self.trigger(g,FILLDRAW)
        self.assertEqual(g.state.draw_history[-1].outcome,'burned');self.assertTrue(g.state.players[1].secrets)
        self.assertFalse(any(d.transformation is not None for d in g.state.draw_history));self.portable(g)

    def test_converted_cast_delivery_overflow_has_no_hand_entry_or_replacement(self):
        g=self.game(mode='fill',deck=(A,CWD,B),watch=True);self.trigger(g);row=self.row(g)
        self.assertIsNone(row.hand_entry_id);self.assertIsNone(row.replacement_id)
        self.assertEqual((g.state.entities[row.entity_id].card_id,g.state.entities[row.entity_id].zone),(BANANA,Zone.GRAVEYARD))
        self.assertEqual(len(g.state.players[2].hand),10);self.portable(g)

    def test_original_hand_departure_during_reveal_does_not_transform_new_residence(self):
        g=self.game(mode='depart',watch=True);self.trigger(g)
        self.assertFalse(any(d.transformation is not None for d in g.state.draw_history))
        self.assertFalse(g.state.players[1].secrets);self.assertEqual(g.state.entities[g.state.draw_history[-1].entity_id].zone,Zone.DECK)

    def test_reveal_wait_restores_before_original_transform_with_advanced_choice_clock(self):
        g=self.game(mode='reveal_wait',deck=(A,CWD,B),watch=True);self.trigger(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        row=self.row(g);self.assertGreater(row.transformation.action,row.action);self.portable(g)

    def test_transform_and_actual_hand_notification_waits_restore_without_duplicate_draw(self):
        for mode in('transform_wait','hand_wait'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,deck=(A,CWD,B),watch=True);self.trigger(g)
                self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
                self.assertEqual(len([e for e in g.events if e.kind=='card_drawn']),2)
                self.assertEqual(len([e for e in g.events if e.kind==EVENT]),1);self.portable(g)

    def test_extra_draw_while_conversion_pending_does_not_redirect_discount(self):
        g=self.game(mode='transform_wait',deck=(A,CWD,B),hand=(DISCOUNT,),watch=True);self.trigger(g,DISCOUNT)
        eid=self.row(g).entity_id;g=self.portable(g);self.choose(g,'extra')
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,0)
        other=g.state.draw_history[-1].entity_id;self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[other]).amount,2)

    def test_action_and_choice_failures_restore_original_history_body_payment_and_rng(self):
        g=self.game(mode='root_fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.trigger(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='transform_wait',deck=(A,CWD,B),watch=True);self.trigger(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.row(g).phase,'done')

    def test_rehashed_snapshot_rejects_forged_hand_link_and_original_cast(self):
        g=self.game(deck=(A,CWD,B));self.trigger(g)
        for key,value in(('hand_entry_id',1),('cast_id',1),('replacement_id',1),('phase','casting')):
            with self.subTest(key=key):
                saved=json.loads(json.dumps(g.snapshot()));saved['state']['draw_history'][-1][key]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('normal','independent-reader'))

    def test_transformation_requires_actual_draw_event_and_revealed_secret_proof(self):
        g=self.game(mode='transform_wait',watch=True);self.trigger(g);row=self.row(g);value=row.transformation
        request=TransformDrawnCard(replace(row,phase='drawing',transformation=None),value.source,value.draw_event,value.before,value.accepted_action)
        request.validate_in_state(g.state,g.registry,g.events)
        with self.assertRaises(ValueError):request.validate_in_state(g.state,g.registry,tuple(e for e in g.events if e.kind!='secret_revealed'))
        with self.assertRaises(ValueError):request.validate_in_state(g.state,g.registry,g.events,allow_committed=False)
        with self.assertRaises(ValueError):validate_transformation(g.state,g.registry,replace(value,draw_id=1))

    def test_waiting_transformation_and_effect_codec_reject_future_allocation(self):
        g=self.game(mode='transform_wait',watch=True);self.trigger(g);row=self.row(g);value=row.transformation
        request=TransformDrawnCard(replace(row,phase='drawing',transformation=None),value.source,value.draw_event,value.before,value.accepted_action)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g.events)
        wire=codec.encode(request);self.assertEqual(codec.decode(wire),request)
        wire['fields']['before']['fields']['zone_epoch']=10**8
        with self.assertRaises(ValueError):codec.decode(wire)
        saved=json.loads(json.dumps(g.snapshot()));saved['state']['draw_history'][-1]['transformation']['before']['zone_epoch']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('transform_wait','independent-reader'))

    def test_owners_second_draw_never_consumes_their_own_secret(self):
        self.mode='normal';g=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(CARD,DRAW,DRAW),deck=(A,)*8,mana=10,max_mana=10),
            PlayerSetup('mage.hero')),seed=646),registry())
        self.play(g,CARD);self.play(g,DRAW);self.play(g,DRAW)
        self.assertEqual(len(g.state.draw_history),2);self.assertTrue(g.state.players[1].secrets)
        self.assertFalse(any(d.transformation is not None for d in g.state.draw_history))

    def test_generation_and_fatigue_do_not_invent_a_second_successful_draw(self):
        g=self.game(deck=(A,),hand=(FILLDRAW,));self.trigger(g,FILLDRAW)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','fatigue'])
        self.assertTrue(g.state.players[1].secrets)

    def test_player_views_hide_original_cast_face_private_receipt_and_native_memory(self):
        g=self.game(deck=(A,CWD,B));self.assertNotIn(CARD,json.dumps(g.for_player(2).observe()))
        self.trigger(g)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for name in(KEY,'_draw_observer','TransformDrawnCard','resolution_frame','rng_state'):self.assertNotIn(name,view)
        self.assertNotIn(CWD,json.dumps(g.for_player(1).observe()))

    def test_real_standard_host_transforms_original_generated_dependency_and_banana_is_playable(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=(CARD,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CORE_CS2_023',),board=('CORE_CS2_182',),
                deck=('CORE_CS2_182','CORE_CS2_182','CORE_CS2_182'),mana=10,max_mana=10)),
            seed=646,generation_context=f.context),f.registry)
        self.play(g,CARD);g.apply(EndTurn(1));self.play(g,'CORE_CS2_023',player=2)
        row=self.row(g);target=self.entity(g,'CORE_CS2_182',2,'board').id;self.play(g,BANANA,target,player=2)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(5,6))
        self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD)


if __name__=='__main__':unittest.main()
