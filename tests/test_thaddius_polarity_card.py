"""Native polarity parameters, owner starts and the original cost pipeline."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest
from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture,FILLER
from hs_sim.cards.thaddius_polarity_card import CARD,EVIDENCE,load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition,CardType,CostSpec,EndTurn,Game,Keyword,PlayerSetup,
    ResolutionError,Scenario,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.cost_polarities import AURA,public_polarity
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Draw,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from tools import card_batch as batch

S='k563.'
ODD,EVEN,ONE,UNIT,WATCH=(S+x for x in ('odd','even','one','unit','watch'))
CTX=GenerationContext('k563-thaddius-native-polarity-test','experimental')


def native(c):
    return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','native-polarity-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def fail(c):raise ResolutionError('k563 deliberate resume failure')
    def observe(c):
        event=c.event
        if mode=='start_wait' and event.kind=='turn_started' and event.player_id==c.player_id:
            subject=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ODD)
            amount=quote_unselected_cost(c.state,r,subject).amount
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',(GainArmor(c.player_id,amount),)),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
        subject=c.state.entities.get(event.source_id or event.target_id)
        if mode=='payment_wait' and event.kind=='card_committed' and subject is not None and subject.card_id==EVEN:
            source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('quiet','Silence source',(Silence(source),)),
                ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    def change_odd_cost(c):
        card=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ODD)
        return (ModifyStoredCost(CardReference.capture(card),CostSpec(delta=-1),c.source_id),)
    scripts={
        'noop':lambda c:(GainArmor(c.player_id,1),),'fail':fail,'observe':observe,
        'copy_current':lambda c:(CopyCard(CardReference.capture(native(c)),c.player_id,mode='current',source_id=c.source_id),),
        'copy_base':lambda c:(CopyCard(CardReference.capture(native(c)),c.player_id,mode='base',source_id=c.source_id),),
        'board_current':lambda c:(CopyMinion(c.target_id,c.player_id,mode='current',cause=SummonCause.capture(c)),),
        'board_base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base',cause=SummonCause.capture(c)),),
        'plain_current':lambda c:(CopyMinion(c.target_id,c.player_id,mode='current'),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),'quiet':lambda c:(Silence(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,UNIT),),'give':lambda c:(AddToHand(c.player_id,CARD,c.source_id),),
        'summon':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),),
        'steal':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'discount':change_odd_cost,
        'top':lambda c:(MoveCard(CardReference.capture(native(c)),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        'reset_top':lambda c:(MoveCard(CardReference.capture(native(c)),c.player_id,Zone.DECK,position='top',reset=True,source_id=c.source_id),),
    }
    targeted={'board_current','board_base','plain_current','bounce','quiet','transform','steal'}
    for name,body in scripts.items():
        r.register_behavior(S+name,body)
        if name not in ('noop','fail','observe'):
            r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name,
                targeting=TargetSpec(kinds=(CardType.MINION,))if name in targeted else None))
    for cid,cost in ((ODD,3),(EVEN,2),(ONE,1)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=S+'noop'))
    r.register_card(CardDefinition(UNIT,'Diagnostic unit',CardType.MINION,cost=3,attack=2,health=3))
    r.register_card(CardDefinition(WATCH,'Polarity boundary observer',CardType.WEAPON,durability=20,
        triggers=tuple(TriggerSpec(k,S+'observe')for k in ('turn_started','card_committed'))))
    r.validate();return replace(fmt,context=CTX)


def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():yield from walk(x)
    elif isinstance(v,list):
        for x in v:yield from walk(x)


def rehash(v):
    v['state_hash']=canonical_hash({k:x for k,x in v.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return v


class ThaddiusPolarityCardTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand=(),*,board=(CARD,),other=(),enemy=(),deck=(FILLER,)*8,mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,
                weapon_card_id=WATCH if mode!='normal'else None),
            PlayerSetup('HERO_08',hand=other,board=enemy,deck=(FILLER,)*8,mana=10,max_mana=10)),
            seed=563,generation_context=CTX),fixture(mode).registry)

    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def price(self,g,cid,player=1):return quote_unselected_cost(g.state,g.registry,self.entity(g,cid,player=player)).amount
    def phase(self,g,identity):return public_polarity(g.state.entities[identity])

    def test_complete_source_both_rules_primary_faces_and_real_undead_taunt(self):
        data=load_batch();rows={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        for item in data['cards']+data['evidence_only']:self.assertEqual(item['record'],rows[item['record']['id']])
        for face in data['official_faces']:batch.check_face(rows[CARD],face['face'],face['locale'],data['display_normalizations'][CARD])
        r=fixture().registry;c=r.card(CARD)
        self.assertEqual((c.cost,c.attack,c.health),(10,11,11));self.assertEqual(c.metadata.tribes,('undead',))
        self.assertEqual(c.keywords,(Keyword.TAUNT,));self.assertEqual(c.cost_auras,(AURA,))
        self.assertTrue(all(cid not in r.cards for cid in EVIDENCE));self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['formal_pool_complete'])

    def test_fresh_native_odd_aura_changes_actual_payment_without_rewriting_card_base(self):
        g=self.game((ODD,EVEN));source=self.entity(g,CARD,zone='board').id
        self.assertEqual((self.phase(g,source),self.price(g,ODD),self.price(g,EVEN)),('odd',1,2))
        self.play(g,ODD);row=g.state.play_history[-1]
        self.assertEqual(row.cost,1);native=next(c for c in row.submitted_cost.quote.contributions if c.ability is not None)
        self.assertEqual((native.polarity_basis,native.ability.cost_polarity.phase),(3,'odd'))
        self.portable(g)

    def test_only_current_controllers_start_flips_board_and_hand_once(self):
        g=self.game((CARD,ODD,EVEN));held=self.entity(g,CARD).id;source=self.entity(g,CARD,zone='board').id
        g.apply(EndTurn(1));self.assertEqual([self.phase(g,i)for i in (held,source)],['odd','odd'])
        g.apply(EndTurn(2));self.assertEqual([self.phase(g,i)for i in (held,source)],['even','even'])
        self.assertEqual((self.price(g,ODD),self.price(g,EVEN)),(3,0));self.play(g,EVEN)
        self.assertEqual(g.state.play_history[-1].cost,0)
        self.cycle(g);self.assertEqual([self.phase(g,i)for i in (held,source)],['odd','odd'])

    def test_deck_rotates_before_actual_start_draw_and_keeps_parameter_when_played(self):
        g=self.game((EVEN,),board=(),deck=(CARD,)+(FILLER,)*5);source=g.state.players[1].deck[0]
        self.assertEqual(self.phase(g,source),'odd');self.cycle(g)
        self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.HAND,'even'))
        self.play(g,CARD);self.assertEqual((g.state.play_history[-1].cost,self.phase(g,source)),(10,'even'))
        self.assertEqual(self.price(g,EVEN),0);self.portable(g)

    def test_late_generated_card_and_plain_summon_start_odd_independent_of_existing_phase(self):
        g=self.game((S+'give',S+'summon'));source=self.entity(g,CARD,zone='board').id;self.cycle(g)
        self.assertEqual(self.phase(g,source),'even');self.play(g,S+'give');self.play(g,S+'summon')
        self.assertEqual(public_polarity(self.entity(g,CARD)),'odd')
        fresh=next(i for i in g.state.players[1].board if i!=source and g.state.entities[i].card_id==CARD)
        self.assertEqual(self.phase(g,fresh),'odd')

    def test_current_hand_copy_keeps_phase_and_base_copy_rebuilds_odd(self):
        g=self.game((CARD,S+'copy_current',S+'copy_base'),board=());source=self.entity(g,CARD).id;self.cycle(g)
        self.assertEqual(self.phase(g,source),'even');self.play(g,S+'copy_current');self.play(g,S+'copy_base')
        cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD]
        self.assertEqual([public_polarity(c)for c in cards],['even','even','odd']);self.portable(g)

    def test_attributed_and_legacy_board_copies_keep_current_phase_and_base_restarts(self):
        g=self.game((S+'board_current',S+'plain_current',S+'board_base'));source=self.entity(g,CARD,zone='board').id
        self.cycle(g)
        for name in ('board_current','plain_current','board_base'):self.play(g,S+name,source)
        self.assertEqual([self.phase(g,i)for i in g.state.players[1].board],['even','even','even','odd'])
        self.portable(g)

    def test_stored_move_to_deck_uses_existing_reset_recipe_and_new_card_draws_correctly(self):
        g=self.game((CARD,S+'reset_top'),board=());source=self.entity(g,CARD).id;self.cycle(g)
        self.assertEqual(self.phase(g,source),'even');self.play(g,S+'reset_top')
        self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.DECK,'odd'))
        self.cycle(g);self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.HAND,'even'))

    def test_plain_physical_move_preserves_current_phase_and_deck_clock_continues(self):
        g=self.game((CARD,S+'top'),board=());source=self.entity(g,CARD).id;self.cycle(g)
        self.play(g,S+'top');self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.DECK,'even'))
        self.cycle(g);self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.HAND,'odd'))

    def test_bounce_resets_phase_on_same_physical_entity(self):
        g=self.game((S+'bounce',));source=self.entity(g,CARD,zone='board').id;self.cycle(g)
        self.assertEqual(self.phase(g,source),'even');self.play(g,S+'bounce',source)
        self.assertEqual((g.state.entities[source].zone,self.phase(g,source)),(Zone.HAND,'odd'));self.portable(g)

    def test_silence_removes_discount_and_phase_and_ordinary_bounce_restores_printed_odd(self):
        g=self.game((S+'quiet',S+'bounce',ODD));source=self.entity(g,CARD,zone='board').id
        self.play(g,S+'quiet',source);self.assertIsNone(self.phase(g,source));self.assertEqual(self.price(g,ODD),3)
        self.play(g,S+'bounce',source);self.assertEqual(self.phase(g,source),'odd')
        self.play(g,CARD);self.assertEqual(self.price(g,ODD),1)

    def test_transform_to_other_native_definition_clears_old_parameter(self):
        g=self.game((S+'transform',ODD));source=self.entity(g,CARD,zone='board').id;self.play(g,S+'transform',source)
        self.assertIsNone(self.phase(g,source));self.assertEqual(self.price(g,ODD),3);self.portable(g)

    def test_control_transfer_keeps_phase_and_future_clock_follows_new_controller(self):
        g=self.game((S+'steal',ODD),other=(EVEN,));source=self.entity(g,CARD,zone='board').id;self.cycle(g)
        self.play(g,S+'steal',source);self.assertEqual((self.phase(g,source),g.state.entities[source].controller),('even',2))
        self.assertEqual(self.price(g,ODD),3);self.assertEqual(self.price(g,EVEN,2),0)
        g.apply(EndTurn(1));self.assertEqual(self.phase(g,source),'odd');self.assertEqual(self.price(g,EVEN,2),2)

    def test_parity_uses_original_after_local_price_and_floor_does_not_create_a_cycle(self):
        g=self.game((ODD,S+'discount'));self.play(g,S+'discount')
        self.assertEqual(self.price(g,ODD),2);self.cycle(g);self.assertEqual(self.price(g,ODD),0)
        self.play(g,ODD);fact=g.state.play_history[-1].submitted_cost.quote
        aura=next(c for c in fact.contributions if c.ability is not None)
        self.assertEqual((fact.local_amount,aura.polarity_basis,aura.ability.cost_polarity.phase),(2,2,'even'))

    def test_two_opposite_sources_share_one_pre_external_operand(self):
        g=self.game((S+'summon',ONE));self.cycle(g);self.play(g,S+'summon')
        self.assertEqual([self.phase(g,i)for i in g.state.players[1].board],['even','odd']);self.play(g,ONE)
        fact=g.state.play_history[-1].submitted_cost.quote
        auras=[c for c in fact.contributions if c.ability is not None]
        self.assertEqual(len(auras),1);self.assertEqual((auras[0].polarity_basis,auras[0].ability.cost_polarity.phase),(1,'odd'))
        self.assertEqual(fact.amount,0)

    def test_owner_start_observer_captures_new_phase_wait_restores_and_bad_branch_is_atomic(self):
        g=self.game((ODD,),mode='start_wait');source=self.entity(g,CARD,zone='board').id;self.cycle(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.phase(g,source),'even')
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)

    def test_paid_zero_quote_keeps_captured_phase_after_waiting_source_silence(self):
        g=self.game((EVEN,),mode='payment_wait');self.cycle(g);self.play(g,EVEN)
        self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'quiet')
        self.assertEqual(g.snapshot(),other.snapshot());row=g.state.play_history[-1]
        aura=next(c for c in row.submitted_cost.quote.contributions if c.ability is not None)
        self.assertEqual((row.cost,aura.polarity_basis,aura.ability.cost_polarity.phase),(0,2,'even'))
        self.assertIsNone(public_polarity(self.entity(g,CARD,zone='board')))

    def test_later_rotation_does_not_rewrite_previous_captured_price(self):
        g=self.game((ODD,));self.play(g,ODD);old=g.state.play_history[-1].submitted_cost;self.cycle(g)
        row=next(p for p in g.state.play_history if p.card_id==ODD)
        self.assertEqual(row.submitted_cost,old)
        aura=next(c for c in old.quote.contributions if c.ability is not None)
        self.assertEqual((aura.ability.cost_polarity.phase,public_polarity(self.entity(g,CARD,zone='board'))),('odd','even'))
        from hs_sim.engine.repeat_provenance import _static_compatible
        current=next(a for a in self.entity(g,CARD,zone='board').abilities if a.cost_polarity is not None)
        self.assertTrue(_static_compatible('ability',aura.ability,current))
        foreign=replace(current,cost_polarity=replace(current.cost_polarity,card_id=UNIT))
        self.assertFalse(_static_compatible('ability',aura.ability,foreign))
        self.assertFalse(_static_compatible('ability',aura.ability,replace(current,source_id=g.state.players[1].hero_id)))
        self.portable(g)

    def test_bad_current_phase_declaration_and_missing_parameter_reject_after_rehash(self):
        g=self.game((ODD,));saved=g.snapshot()
        for mode in ('phase','declaration','missing'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);states=[v for v in walk(bad)if isinstance(v.get('cost_polarity'),dict)]
                self.assertTrue(states)
                for a in states:
                    if mode=='phase':a['cost_polarity']['phase']='unknown'
                    elif mode=='declaration':a['cost_polarity']['card_id']=UNIT
                    else:a['cost_polarity']=None
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader').registry)

    def test_bad_original_basis_captured_phase_and_old_schema_are_rejected(self):
        g=self.game((ODD,));self.play(g,ODD);saved=g.snapshot()
        for mode in ('basis','phase','missing'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);rows=[v for v in walk(bad)if v.get('kind')=='cost_aura'and v.get('polarity_basis')is not None]
                self.assertTrue(rows)
                for c in rows:
                    if mode=='basis':c['polarity_basis']=2
                    elif mode=='phase':c['ability']['cost_polarity']['phase']='even'
                    else:c['polarity_basis']=None
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader').registry)
        bad=deepcopy(saved);bad['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture().registry)

    def test_public_phase_is_minimal_hidden_enemy_hand_stays_private_and_queries_are_pure(self):
        g=self.game((CARD,ODD),other=(CARD,));saved=g.snapshot()
        for player in (1,2):
            view=g.for_player(player).observe();text=json.dumps(view)
            self.assertNotIn('"polarity_basis"',text);self.assertNotIn('"cost_polarity_profiles"',text)
            self.assertFalse(any(v.get('zone')=='hand'and v.get('controller')!=player and 'cost_polarity'in v for v in walk(view)))
            self.assertTrue(any(v.get('card_id')==CARD and v.get('cost_polarity')=='odd'for v in walk(view)))
        self.assertEqual(self.price(g,ODD),1);self.assertEqual(g.snapshot(),saved)

    def test_real_frontier_generation_set_one_then_current_odd_aura_makes_zero_with_wait_restore(self):
        r=fixture().registry;members=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([(m.card_id,m.weight)for m in members],[(CARD,1)])
        g=self.game(('GDB_857',ODD));self.play(g,'GDB_857');other=self.portable(g)
        for game in (g,other):
            self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==CARD))
            source=self.play(game,CARD);self.assertEqual(game.state.play_history[-1].cost,0)
            self.assertEqual(self.phase(game,source),'odd');self.assertIn(Keyword.TAUNT,game.state.entities[source].keywords)
            self.assertEqual(self.price(game,ODD),0)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)


if __name__=='__main__':unittest.main()
