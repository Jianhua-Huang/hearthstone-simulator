"""One real conditional generation rule using the existing pool and cost APIs."""
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, ChoicePurpose,
    CostSpec, DeckCondition, DeckSpec, EndTurn, Game, MatchSetup, OpeningHook,
    PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, UnknownDeckFacts, Zone)
from hs_sim.engine.deck_conditions import CheckDeckCondition
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption,
    Destroy, Draw, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery, resolve_candidates, sample_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DestroyDeckMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry

NATIVE='JAIL_806'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/starting-deck-no-spells-basics.json'
PIN='132f56f858e3d9916cb1bab0b5eb3c823173f1aadcb9aa898cd0338153014dc3'
CONDITION=DeckCondition('starting','no_spells')
QUERY=PoolQuery(kinds=(CardType.SPELL,),min_cost=5)
CONTEXT=GenerationContext('synthetic-test-target','experimental')
POOL='cgs.finite-spell-probes'
SPELLS=('cgs.spell.4','cgs.spell.5','cgs.spell.7','cgs.spell.8')
ELIGIBLE=SPELLS[1:]
DEFAULT_MEMBERS=SPELLS+('cgs.big.minion',)


def evidence():
    support=json.loads(SUPPORT.read_bytes())
    if canonical_digest(support)!=PIN or [r['id'] for r in support['records']]!=[NATIVE]:
        raise ValueError('Complete native raw evidence changed')
    row=support['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Complete native row changed')
    return row['data']


def native_body(c):
    def give(cost=None):
        return GenerateFromPool(c.player_id,POOL,QUERY,count=1,source_id=c.source_id,cost=cost)
    return (CheckDeckCondition(c.player_id,CONDITION,(give(CostSpec(delta=-5)),),(give(),)),)


def registry(members=None, *, version='v1'):
    raw=evidence();r=opening_registry()
    for kind in ('hero','power'):
        r.register_card(CardDefinition('cgs.rogue.'+kind,kind,
            CardType.HERO if kind=='hero' else CardType.HERO_POWER,
            health=30 if kind=='hero' else 0,cost=0 if kind=='hero' else 2,
            initial_hero_power='cgs.rogue.power' if kind=='hero' else None,
            on_use='power' if kind=='power' else None,
            metadata=metadata(CardClass.ROGUE,collectible=False)))
    r.register_behavior('cgs.native',native_body)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,
        cost=6,attack=6,health=6,battlecry='cgs.native',
        metadata=metadata(CardClass.ROGUE,rarity=Rarity.RARE,tribes=())))
    r.register_behavior('cgs.spell',lambda c:(GainArmor(c.player_id,1),))
    for cid,cost,cls in zip(SPELLS,(4,5,7,8),
            (CardClass.ROGUE,CardClass.MAGE,CardClass.DRUID,CardClass.ROGUE)):
        definition=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play='cgs.spell',metadata=metadata(cls))
        r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
    big=CardDefinition('cgs.big.minion','Finite type-filter probe',CardType.MINION,
        cost=7,attack=1,health=1,metadata=metadata())
    r.register_card(big);r.register_pool_card(PoolCard.from_definition(big))
    r.register_pool_card(PoolCard('cgs.unknown',CardType.SPELL,7,metadata(CardClass.ROGUE)))
    r.register_pool(PoolDefinition(POOL,version,CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid) for cid in(DEFAULT_MEMBERS if members is None else members)),complete=False))

    def fault(c):raise RuntimeError('Deliberate conditional generation continuation failure')
    r.register_behavior('cgs.fault',fault)
    def pause(c):
        return RequestChoice(c.player_id,(
            ChoiceOption('go','Continue',()),
            ChoiceOption('fault','Fail', (InvokeBehavior('cgs.fault',c.source_id,c.player_id),)),
        ),c.source_id)
    def before(c):return (pause(c),) if c.event.player_id==c.player_id else ()
    def after(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id not in ELIGIBLE:return ()
        # This diagnostic observes creation before the acquisition checkpoint.
        assert local_cost(c.state.entities[c.event.target_id])[0]>=0
        return (pause(c),)
    def fill(c):
        return tuple(AddToHand(c.player_id,'card.40',c.source_id)
            for _ in range(10-len(c.state.players[c.player_id].hand))) if c.event.player_id==c.player_id else ()
    for name,event,body in(('before','mana_spent',before),('after','card_created',after),('fill','battlecry_started',fill)):
        r.register_behavior('cgs.watch.'+name,body)
        r.register_card(CardDefinition('cgs.watch.'+name,name,CardType.MINION,health=1,
            triggers=(TriggerSpec(event,'cgs.watch.'+name),),metadata=metadata()))
    def native(c):return max(e.id for e in c.state.entities.values() if e.card_id==NATIVE and e.controller==c.player_id)
    def last_spell(c):
        return c.state.entities[next(i for i in reversed(c.state.players[c.player_id].hand)
            if c.state.entities[i].card_id in ELIGIBLE)]
    scripts={
        'add':lambda c:(AddToDeck(c.player_id,'cgs.spell.7','random',c.source_id),AddToHand(c.player_id,'cgs.spell.7',c.source_id)),
        'clear':lambda c:(DestroyDeckMatching(c.player_id,count=40,reveal=False),),
        'existing':lambda c:(AddToHand(c.player_id,'cgs.spell.7',c.source_id),),
        'silence':lambda c:(Silence(native(c)),),
        'destroy':lambda c:(Destroy(native(c),c.source_id),),
        'bounce':lambda c:(ReturnToHand(native(c)),),
        'copy.current':lambda c:(CopyCard(CardReference.capture(last_spell(c)),c.player_id,mode='current'),),
        'copy.base':lambda c:(CopyCard(CardReference.capture(last_spell(c)),c.player_id,mode='base'),),
        'move':lambda c:(MoveCard(CardReference.capture(last_spell(c)),c.player_id,Zone.DECK,'top'),Draw(c.player_id)),
        'reset':lambda c:(MoveCard(CardReference.capture(last_spell(c)),c.player_id,Zone.DECK,'top',reset=True),Draw(c.player_id)),
    }
    for name,body in scripts.items():
        cid='cgs.tool.'+name;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=1,battlecry=cid,metadata=metadata()))
    def prepare(c):
        original=c.state.players[c.player_id].original_deck
        return (ChangeManaCrystals(c.player_id,9),AddToHand(c.player_id,NATIVE,c.source_id),
            *(AddToHand(c.player_id,cid,c.source_id) for cid in original if cid.startswith('cgs.tool.')),
            *(Summon(c.player_id,cid) for cid in original if cid.startswith('cgs.watch.')))
    r.register_behavior('cgs.prepare',prepare)
    r.register_card(CardDefinition('cgs.prep','Explicit experimental hand/clock preparation',CardType.MINION,
        health=1,metadata=metadata(),opening_hooks=(OpeningHook('after_mulligan','cgs.prepare'),)))
    return r


class ConditionalGeneratedSpellCostTests(unittest.TestCase):
    def match(self,extra=(),*,tools=(),watcher=None,other_extra=(),first=1,members=None):
        r=registry(members)
        def cards(extra,tools=(),watcher=None):
            prefix=('cgs.prep',)+tuple(extra)+tuple('cgs.tool.'+n for n in tools)
            if watcher:prefix+=('cgs.watch.'+watcher,)
            return prefix+tuple(f'card.{i}' for i in range(1,31-len(prefix)))
        decks=tuple(DeckSpec('cgs.rogue.hero','cgs.rogue.power',CardClass.ROGUE,c)
            for c in(cards(extra,tools,watcher),cards(other_extra)))
        g=Game.from_decks(MatchSetup(decks,policy(r),'coin',85,first),r)
        while g.state.pending_choice:
            q=g.state.pending_choice
            self.assertEqual(q.purpose,ChoicePurpose.MULLIGAN)
            g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def source(self,g,player=1):
        return max(e.id for e in g.state.entities.values() if e.card_id==NATIVE and e.controller==player)
    def play(self,g,player=1):return g.apply(PlayCard(player,self.source(g,player)))
    def tool(self,g,name,player=1):
        i=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id=='cgs.tool.'+name)
        return g.apply(PlayCard(player,i))
    def generated(self,g,player=1):
        source=self.source(g,player)
        return g.state.entities[next(e.target_id for e in reversed(g.events) if e.kind=='card_created' and e.source_id==source)]
    def choose(self,g,option='go'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g):
        members=tuple(m.card_id for m in g.registry.pool(POOL,CONTEXT).members)
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry(members))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(members)).snapshot(),saved)
        return restored

    def test_complete_native_metadata_and_existing_effect_expression(self):
        raw=evidence();card=registry().card(NATIVE)
        original=next(r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes()) if r['id']==NATIVE)
        self.assertEqual(raw,original)
        self.assertEqual((card.cost,card.attack,card.health),(6,6,6))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.tribes),((CardClass.ROGUE,),Rarity.RARE,()))
        self.assertEqual(card.battlecry,'cgs.native');self.assertIsNone(card.targeting)

    def test_true_condition_randomly_gets_exactly_one_spell_from_printed_five_or_more(self):
        g=self.match();candidates=resolve_candidates(g.registry,CONTEXT,POOL,QUERY)
        self.assertEqual(tuple(m.card_id for m in candidates),ELIGIBLE)
        before=len(g.state.players[1].hand);oracle=random.Random();oracle.setstate(g._rng.getstate())
        expected=sample_candidates(oracle,candidates,1,replacement=True)
        self.play(g);card=self.generated(g)
        self.assertEqual((card.card_id,),(expected));self.assertEqual(g._rng.getstate(),oracle.getstate())
        self.assertEqual(len(g.state.players[1].hand),before)
        self.assertEqual(g.quote_cost(card.id).amount,g.registry.card(card.card_id).cost-5)
        self.assertEqual(g.state.players[1].mana,4)

    def test_initial_five_and_eight_cost_spells_use_flat_minus_five_with_zero_floor(self):
        for cid,amount in(('cgs.spell.5',0),('cgs.spell.8',3)):
            with self.subTest(cid=cid):
                g=self.match(members=(cid,));self.play(g);card=self.generated(g)
                self.assertEqual(local_cost(card)[0],amount);self.assertEqual(g.quote_cost(card.id).amount,amount)
                self.assertEqual(len(card.enchantments),1);self.assertEqual(card.enchantments[0].cost,-5)

    def test_false_condition_still_gets_one_spell_at_original_cost(self):
        g=self.match(('cgs.spell.8',),members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        self.assertEqual((card.card_id,g.quote_cost(card.id).amount),('cgs.spell.7',7))
        self.assertEqual(card.enchantments,[]);self.assertEqual(g.state.players[1].cost_modifiers,[])

    def test_only_generated_physical_instance_changes_existing_same_id_is_untouched(self):
        g=self.match(tools=('existing',),members=('cgs.spell.7',));self.tool(g,'existing')
        existing=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='cgs.spell.7')
        self.play(g);generated=self.generated(g)
        self.assertNotEqual(existing,generated.id)
        self.assertEqual((g.quote_cost(existing).amount,g.quote_cost(generated.id).amount),(7,2))
        self.assertEqual(g.state.players[1].cost_modifiers,[])
        self.assertEqual(g.state.entities[existing].enchantments,[])

    def test_later_spell_in_current_deck_and_hand_does_not_change_starting_condition(self):
        g=self.match(tools=('add',),members=('cgs.spell.7',));self.tool(g,'add')
        self.assertTrue(any(g.state.entities[i].card_id=='cgs.spell.7' for i in g.state.players[1].deck))
        self.play(g);self.assertEqual(g.quote_cost(self.generated(g).id).amount,2)

    def test_clearing_current_deck_does_not_erase_original_spell(self):
        g=self.match(('cgs.spell.8',),tools=('clear',),members=('cgs.spell.7',));self.tool(g,'clear')
        self.assertEqual(g.state.players[1].deck,[])
        self.play(g);self.assertEqual(g.quote_cost(self.generated(g).id).amount,7)

    def test_condition_uses_actual_controller_and_not_opponents_original_deck(self):
        g=self.match(('cgs.spell.8',),first=2,members=('cgs.spell.7',));other_mana=g.state.players[1].mana;self.play(g,2)
        card=self.generated(g,2);self.assertEqual((card.controller,g.quote_cost(card.id).amount),(2,2))
        self.assertEqual((g.state.players[1].mana,g.state.players[2].mana),(other_mana,4))

    def test_public_native_and_generated_spell_commands_pay_each_card_once(self):
        g=self.match(members=('cgs.spell.7',));api=g.for_player(1)
        for cid,cost in((NATIVE,6),('cgs.spell.7',2)):
            offered=api.legal_actions();before=g.state.players[1].mana
            ref=next(c['ref'] for c in offered['observation']['players'][0]['hand'] if c.get('card_id')==cid)
            action=next(a for a in offered['actions'] if a['type']=='play_card' and a['card']==ref)
            result=api.submit({'revision':offered['revision'],'action':action})
            self.assertTrue(result['accepted']);self.assertIsNone(result['error'])
            self.assertEqual(g.state.players[1].mana,before-cost)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)

    def test_source_silence_and_death_do_not_remove_the_generated_instances_cost(self):
        g=self.match(tools=('silence','destroy'),members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        self.tool(g,'silence');self.assertEqual(g.quote_cost(card.id).amount,2)
        self.tool(g,'destroy');self.assertEqual(g.state.entities[self.source(g)].zone,Zone.GRAVEYARD)
        self.assertEqual(g.quote_cost(card.id).amount,2);self.portable(g)

    def test_later_manual_native_play_creates_an_independent_discounted_card(self):
        g=self.match(tools=('bounce',),members=('cgs.spell.7',));self.play(g);first=self.generated(g)
        self.tool(g,'bounce');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);second=self.generated(g)
        self.assertNotEqual(first.id,second.id)
        self.assertEqual((g.quote_cost(first.id).amount,g.quote_cost(second.id).amount),(2,2))
        self.assertNotEqual(first.enchantments[0].id,second.enchantments[0].id)
        self.assertEqual(g.state.players[1].cost_modifiers,[])

    def test_current_copy_keeps_local_cost_and_base_copy_uses_printed_cost(self):
        g=self.match(tools=('copy.current','copy.base'),members=('cgs.spell.7',));self.play(g)
        original=self.generated(g);self.tool(g,'copy.current')
        current=g.state.entities[g.state.players[1].hand[-1]]
        self.tool(g,'copy.base');base=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((g.quote_cost(original.id).amount,g.quote_cost(current.id).amount,g.quote_cost(base.id).amount),(2,2,7))
        self.assertEqual(len({original.id,current.id,base.id}),3)
        self.assertNotEqual(original.enchantments[0].id,current.enchantments[0].id);self.assertEqual(base.enchantments,[])
        self.portable(g)

    def test_physical_zone_move_and_explicit_reset_use_original_lifecycle_policies(self):
        for name,amount in(('move',2),('reset',7)):
            with self.subTest(name=name):
                g=self.match(tools=(name,),members=('cgs.spell.7',));self.play(g);card=self.generated(g)
                self.tool(g,name);self.assertEqual(card.id,g.state.players[1].hand[-1])
                self.assertEqual(g.quote_cost(card.id).amount,amount)

    def test_indefinite_instance_discount_survives_natural_turn_boundaries(self):
        g=self.match(members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.quote_cost(card.id).amount,2);self.assertIsNone(card.enchantments[0].expires_turn)

    def test_before_generation_paid_wait_restores_and_then_samples_once(self):
        g=self.match(watcher='before',members=('cgs.spell.7',));before=g._rng.getstate();self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual(g._rng.getstate(),before)
        restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.quote_cost(self.generated(g).id).amount,2);self.assertEqual(g.state.players[1].mana,4)
        self.portable(g)

    def test_after_creation_wait_keeps_already_installed_cost_and_original_sample(self):
        g=self.match(watcher='after',members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(local_cost(card)[0],2)
        waiting_rng=g._rng.getstate();restored=self.portable(g)
        self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g._rng.getstate(),waiting_rng)
        self.assertEqual(self.generated(g).id,card.id);self.assertEqual(g.quote_cost(card.id).amount,2)
        self.portable(g)

    def test_failed_before_generation_choice_preserves_the_paid_waiting_boundary(self):
        g=self.match(watcher='before');self.play(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].mana,4)
        self.choose(g);self.assertEqual(g.quote_cost(self.generated(g).id).amount,g.registry.card(self.generated(g).card_id).cost-5)

    def test_failed_after_creation_choice_keeps_the_same_card_rng_and_cost(self):
        g=self.match(watcher='after');self.play(g);saved=g.snapshot();card=self.generated(g)
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.quote_cost(card.id).amount,g.registry.card(card.card_id).cost-5)
        self.choose(g);self.assertEqual(self.generated(g).id,card.id)

    def test_full_hand_burn_keeps_atomic_initial_cost_and_does_not_redraw(self):
        g=self.match(watcher='fill',members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(card.zone,Zone.GRAVEYARD)
        self.assertEqual(local_cost(card)[0],2)
        burns=[e for e in g.events if e.kind=='card_burned' and e.source_id==self.source(g)]
        self.assertEqual([e.target_id for e in burns],[card.id]);self.portable(g)

    def test_empty_eligible_finite_pool_keeps_rng_and_still_finishes_paid_native(self):
        g=self.match(members=('cgs.spell.4','cgs.big.minion'));before=g._rng.getstate();count=len(g.state.players[1].hand)
        self.play(g);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(len(g.state.players[1].hand),count-1)
        self.assertEqual((g.state.players[1].mana,g.state.entities[self.source(g)].zone),(4,Zone.BOARD))

    def test_any_unimplemented_eligible_candidate_aborts_without_filtering_or_rng(self):
        g=self.match(members=('cgs.spell.7','cgs.unknown'));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition') as failed:self.play(g)
        self.assertIsInstance(failed.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),saved)

    def test_scenario_without_bound_starting_facts_is_rejected_atomically(self):
        r=registry();g=Game.from_scenario(Scenario((PlayerSetup('cgs.rogue.hero',hand=(NATIVE,),mana=10,max_mana=10),
            PlayerSetup('cgs.rogue.hero')),generation_context=CONTEXT),r);saved=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_pool_fingerprint_is_bound_and_formal_context_has_no_experimental_fallback(self):
        g=self.match(members=('cgs.spell.7',));self.play(g);saved=g.snapshot()
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(('cgs.spell.7',),version='v2'))
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(g.registry,GenerationContext(CONTEXT.target_id,'standard'),POOL,QUERY)

    def test_private_generation_and_cost_do_not_leak_into_opponent_observations(self):
        g=self.match(members=('cgs.spell.7',));self.play(g);card=self.generated(g)
        before=g.snapshot();public=json.dumps(g.observe(2))+json.dumps(g.player_events(2))+json.dumps(g.for_player(2).legal_actions())
        self.assertNotIn(card.card_id,public)
        for key in('rng_state','original_deck','enchantments','resolution_frame','generation_candidates'):
            self.assertNotIn('"'+key+'"',public)
        own=next(c for c in g.observe(1)['players'][0]['hand'] if c.get('card_id')==card.card_id)
        self.assertEqual(own['card_id'],card.card_id)
        self.assertEqual(g.snapshot(),before);self.portable(g)
