"""One native fixed-pool producer with typed sampling and actual half choices."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (CardClass,CardDefinition,CardType,Game,IllegalAction,PlayCard,PlayerSetup,
    Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.model import EndTurnSpec,Keyword,ChoicePurpose
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate,recipe_from_id
from hs_sim.engine.assemble_offers import Assemble,ResolveAssemble,option_rows,validate_offer
from hs_sim.engine.effects import AddToHand,GainArmor
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from opening_fixtures import metadata

ALL=('battlecry','deathrattle','end_turn')

def registry(missing=False,unknown=False):
    r=Registry('native-assembly-fixed-pool-experimental-v1')
    r.register_card(CardDefinition('hero','Diagnostic Mage',CardType.HERO,health=60,metadata=metadata(CardClass.MAGE,collectible=False)))
    for key,n in(('a',2),('b',5),('c',3),('w',7)):
        r.register_behavior(key,lambda c,n=n:(GainArmor(c.player_id,n),))
    cards=(CardDefinition('a','Primary A',CardType.MINION,cost=2,attack=2,health=3,keywords=(Keyword.TAUNT,),deathrattle='a',metadata=metadata()),
        CardDefinition('b','Donor B',CardType.MINION,cost=4,attack=4,health=4,battlecry='b',metadata=metadata()),
        CardDefinition('c','Donor C',CardType.MINION,cost=4,attack=3,health=5,triggers=(TriggerSpec('turn_ended','c',EndTurnSpec()),),metadata=metadata(CardClass.MAGE)),
        CardDefinition('w','Other Warrior',CardType.MINION,cost=2,attack=1,health=2,battlecry='w',metadata=metadata(CardClass.WARRIOR)))
    for card in cards:r.register_card(card)
    for key,kind,kw in(('a','deathrattle',(Keyword.TAUNT,)),('b','battlecry',()),('c','end_turn',()),('w','battlecry',())):
        if missing and key=='c':continue
        r.register_assemble_template(AssembleTemplate(key,AssemblePrefix(kind,kw,EndTurnSpec()if kind=='end_turn'else None),AssembleSuffix(key,ALL)))
    for card in cards:r.register_pool_card(PoolCard.from_definition(card))
    members=tuple(PoolMember(key)for key in('a','b','c','w'))
    if unknown:
        r.register_pool_card(PoolCard('unknown',CardType.MINION,2,metadata()))
        members=(*members,PoolMember('unknown'))
    r.register_pool(PoolDefinition('pool','v1','assembly-experiment','experimental',members))
    r.register_pool(PoolDefinition('small','v1','assembly-experiment','experimental',(PoolMember('a'),PoolMember('b'))))
    def spec(c,**kwargs):return Assemble(c.player_id,'pool',c.source_id,PoolQuery(max_cost=2),**kwargs)
    bodies={'assemble':lambda c:(spec(c),),'foreign':lambda c:(spec(c),),
        'full':lambda c:(AddToHand(c.player_id,'a',c.source_id),spec(c)),
        'keep':lambda c:(spec(c,keep_policy='offer'),),
        'small.error':lambda c:(replace(spec(c),pool_id='small'),),
        'small.available':lambda c:(replace(spec(c),pool_id='small',small_policy='available'),),
        'empty.error':lambda c:(replace(spec(c),primary_query=PoolQuery(max_cost=0)),),
        'empty.skip':lambda c:(replace(spec(c),primary_query=PoolQuery(max_cost=0),empty_policy='skip'),),
        'trait':lambda c:(spec(c,primary_trait='deathrattle'),),
        'no.trait':lambda c:(spec(c,primary_trait='battlecry',empty_policy='skip'),),
        'repeat':lambda c:(spec(c),spec(c)),}
    for key,fn in bodies.items():
        r.register_behavior(key,fn);r.register_card(CardDefinition(key,'Diagnostic '+key,CardType.SPELL,cost=1,on_play=key,
            metadata=metadata(CardClass.WARRIOR if key=='foreign'else CardClass.MAGE)))
    return r

class AssembleOfferTests(unittest.TestCase):
    def game(self,hand=('assemble',),missing=False,unknown=False,seed=166):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,deck=('a',)*10,max_mana=10,mana=10),
            PlayerSetup('hero',hand=('foreign',),deck=('a',)*10,max_mana=10,mana=10)),seed=seed,
            generation_context=GenerationContext('assembly-experiment','experimental')),registry(missing,unknown))
    def play(self,g,name):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name);return g.apply(PlayCard(1,eid))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return s
    def offer(self,g):return g._frame.options[0].effects[0].offer
    def pick(self,g,oid=None):
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,(oid or choice.options[0].id,)))

    def test_declared_domain_and_unknown_policies_are_strict(self):
        value=Assemble(1,'pool')
        for kw in({'primary_query':PoolQuery(kinds=(CardType.SPELL,))},{'primary_query':PoolQuery(class_mode='other')},
                {'primary_trait':'unknown'},{'small_policy':'repeat'},{'empty_policy':'white'},{'keep_policy':'auto'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(value,**kw)

    def test_primary_current_class_cost_band_two_donors_four_half_options(self):
        g=self.game();self.play(g,'assemble');offer=self.offer(g)
        self.assertEqual(offer.primary_card_id,'a');self.assertEqual(offer.primary_candidates,('a',))
        self.assertEqual(set(offer.secondary_card_ids),{'b','c'});self.assertEqual(len(g.state.pending_choice.options),4)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.ASSEMBLE);self.portable(g)

    def test_foreign_spell_still_uses_current_hero_class(self):
        g=self.game(hand=('foreign',));self.play(g,'foreign');offer=self.offer(g)
        self.assertNotIn('w',offer.primary_candidates);self.assertNotIn('w',offer.secondary_candidates)
        self.assertIn('c',offer.secondary_candidates);self.portable(g)

    def test_nine_and_ten_cost_primaries_allow_eight_cost_secondary(self):
        from hs_sim.engine.assemble_offers import candidates
        r=registry()
        for cid,cost,kind,body in(('nine',9,'deathrattle','a'),('ten',10,'end_turn','c'),('eight',8,'battlecry','b'),('twelve',12,'battlecry','b')):
            prefix=AssemblePrefix(kind,end_turn=EndTurnSpec()if kind=='end_turn'else None)
            r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=2,
                battlecry=body if kind=='battlecry'else None,deathrattle=body if kind=='deathrattle'else None,
                triggers=(TriggerSpec('turn_ended',body,prefix.end_turn),)if kind=='end_turn'else(),metadata=metadata()))
            r.register_assemble_template(AssembleTemplate(cid,prefix,AssembleSuffix(body,ALL)))
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
        r.register_pool(PoolDefinition('high','v1','assembly-experiment','experimental',tuple(PoolMember(cid)for cid in('eight','nine','ten','twelve'))))
        g=Game.from_scenario(Scenario((PlayerSetup('hero'),PlayerSetup('hero')),generation_context=GenerationContext('assembly-experiment','experimental')),r)
        spec=Assemble(1,'high');context=g._generation_context
        for primary in('nine','ten'):
            pool=tuple(m.card_id for m in candidates(r,context,g.state,spec,primary))
            self.assertIn('eight',pool)
            if primary=='nine':self.assertNotIn('twelve',pool)
            else:self.assertIn('twelve',pool)

    def test_each_actual_half_selection_delivers_its_immutable_face(self):
        initial=self.game();self.play(initial,'assemble');s=self.portable(initial)
        for option in initial.state.pending_choice.options:
            with self.subTest(oid=option.id):
                g=Game.from_snapshot(deepcopy(s),registry());self.pick(g,option.id)
                cid=g.state.entities[g.state.players[1].hand[-1]].card_id;recipe=recipe_from_id(cid)
                self.assertEqual(recipe.primary_card_id,'a');self.assertEqual(cid,option.card_id)
                self.assertEqual((g.registry.card(cid).cost,g.registry.card(cid).attack,g.registry.card(cid).health),(2,2,3));self.portable(g)

    def test_selection_and_restore_do_not_resample_or_consume_rng(self):
        g=self.game();self.play(g,'assemble');offer=self.offer(g);rng=g.snapshot()['rng_state'];s=self.portable(g)
        h=Game.from_snapshot(s,registry());self.pick(g);self.pick(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertNotEqual(offer.rng_before,offer.rng_after);self.portable(g)

    def test_delivery_then_paid_new_card_uses_native_payload(self):
        g=self.game();self.play(g,'assemble');oid=next(oid for oid,_,cid in option_rows(g.registry,self.offer(g))if g.registry.card(cid).battlecry=='a')
        self.pick(g,oid);cid=g.state.entities[g.state.players[1].hand[-1]].card_id;self.play(g,cid)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_full_hand_delivery_uses_existing_overflow(self):
        from hs_sim.engine import Zone
        g=self.game(hand=('full',)+('a',)*9);self.play(g,'full');self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(any(e.card_id.startswith('assemble:') and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()))
        self.portable(g)

    def test_keep_is_explicit_and_delivers_original_primary(self):
        g=self.game(hand=('keep',));self.play(g,'keep');self.assertEqual(len(g.state.pending_choice.options),5)
        self.pick(g,'keep');self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,'a');self.portable(g)

    def test_small_pool_error_rolls_back_payment_and_rng(self):
        g=self.game(hand=('small.error',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'small.error')
        self.assertEqual(g.snapshot(),before)

    def test_small_available_policy_is_explicit(self):
        g=self.game(hand=('small.available',));self.play(g,'small.available')
        self.assertEqual(self.offer(g).secondary_card_ids,('b',));self.assertEqual(len(g.state.pending_choice.options),2)
        self.pick(g);self.portable(g)

    def test_empty_error_and_skip_do_not_hide_unknown_content(self):
        g=self.game(hand=('empty.error',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'empty.error')
        self.assertEqual(g.snapshot(),before)
        g=self.game(hand=('empty.skip',));rng=g.snapshot()['rng_state'];self.play(g,'empty.skip')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_trait_filters_original_primary_only(self):
        g=self.game(hand=('trait',));self.play(g,'trait');offer=self.offer(g)
        self.assertEqual(offer.primary_candidates,('a',));self.assertEqual(set(offer.secondary_card_ids),{'b','c'});self.portable(g)
        g=self.game(hand=('no.trait',));self.play(g,'no.trait');self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_missing_template_and_unknown_adapter_raise_and_restore_rng(self):
        for kw in({'missing':True},{'unknown':True}):
            with self.subTest(kw=kw):
                g=self.game(**kw);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,'assemble')
                self.assertEqual(g.snapshot(),before)

    def test_two_requests_have_independent_original_samples(self):
        g=self.game(hand=('repeat',));self.play(g,'repeat');first=self.offer(g);self.portable(g);self.pick(g)
        second=self.offer(g);self.assertEqual(first.rng_after,second.rng_before)
        self.assertNotEqual(first.rng_before,second.rng_after);self.portable(g);self.pick(g);self.portable(g)

    def test_pending_choice_does_not_accept_other_actions_or_wrong_player(self):
        g=self.game();self.play(g,'assemble');before=g.snapshot();choice=g.state.pending_choice
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(2,choice.id,(choice.options[0].id,)))
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,choice.id,('unknown',)))
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_receipt_rejects_changed_inventory_selection_or_rng(self):
        g=self.game();self.play(g,'assemble');offer=self.offer(g)
        for kw in({'primary_candidates':('b',)},{'secondary_card_ids':tuple(reversed(offer.secondary_card_ids))},
                {'secondary_candidates':('b',)},{'rng_after':offer.rng_before}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):validate_offer(g.registry,g._generation_context,replace(offer,**kw))

    def test_original_acceptance_cannot_belong_to_future_state_or_another_deck(self):
        from hs_sim.engine.assemble_offers import validate_current
        g=self.game();self.play(g,'assemble');offer=self.offer(g)
        for field in('turn','action_number','next_entity_id','next_order','next_attachment_id','next_choice_id'):
            bad=deepcopy(offer);setattr(bad.before,field,getattr(g.state,field)+1)
            with self.subTest(field=field),self.assertRaises(ValueError):validate_current(bad,g.state)
        bad=deepcopy(offer);bad.before.players[1].original_deck=('b',)
        with self.assertRaises(ValueError):validate_current(bad,g.state)

    def test_pending_trimmed_options_or_changed_purpose_rejected(self):
        g=self.game();self.play(g,'assemble');saved=self.portable(g)
        # Frame typed payloads are reconstructed through the public snapshot codec.
        bad=deepcopy(saved);bad['state']['pending_choice']['options'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        bad=deepcopy(saved);bad['state']['pending_choice']['purpose']='effect'
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_private_inventory_and_before_state_not_in_player_views(self):
        g=self.game();self.play(g,'assemble');before=g.snapshot()
        for seat in(1,2):
            view=json.dumps(g.for_player(seat).observe())
            for hidden in('primary_candidates','secondary_candidates','rng_before','rng_after','assemble_templates'):
                self.assertNotIn(hidden,view)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_player_command_selects_half_through_existing_opaque_refs(self):
        g=self.game();self.play(g,'assemble');p=g.for_player(1);listing=p.legal_actions()
        action=next(a for a in listing['actions']if a['type']=='select_choice')
        self.assertTrue(p.submit({'revision':listing['revision'],'action':action})['accepted']);self.portable(g)

if __name__=='__main__':unittest.main()
