"""Finite native probe of an even budget using captured ordinary stored buffs.

Remainders follow current deck order in this internal policy. Public logs confirm
50 Attack/50 Health and 17/17/16, but do not authenticate the hidden order or CN.
"""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, ChoicePurpose,
    DeckMinionCostSumCondition, DeckSpec, EndTurn, Game, MatchSetup, OpeningHook,
    PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    TriggerSpec, UnknownDeckFacts, Zone)
from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.deck_conditions import CheckDeckCondition
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption,
    Destroy, Draw, InvokeBehavior, RequestChoice, Silence, Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DestroyDeckMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry

NATIVE='CATA_213'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/starting-deck-minion-cost-sum-basics.json'
PIN='9fcc48a7da967a9ab6d99b8f574fc70841d651101b49c8384b06a7d81b159c95'
CONDITION=DeckMinionCostSumCondition(100,'printed')
SCOPE=MinionScope(zones=(Zone.DECK,))
CURRENT=('dsa.m.a','dsa.m.b','dsa.m.c')


def evidence():
    packet=json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet)!=PIN or [r['id'] for r in packet['records']]!=[NATIVE]:
        raise ValueError('Complete native raw evidence changed')
    row=packet['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Complete native row changed')
    return row['data']


def allocation(c, registry):
    refs=minion_references(c.state,registry,c.player_id,SCOPE,c.source_id)
    if not refs:return ()
    each,remainder=divmod(50,len(refs))
    effects=[]
    for index,ref in enumerate(refs):
        amount=each+(index<remainder)
        if amount:
            # Preserve separate ordinary Attack/Health attachments as in the log.
            effects.extend((BuffStoredCard(ref,attack=amount,source_id=c.source_id),
                BuffStoredCard(ref,health=amount,source_id=c.source_id)))
    return tuple(effects)


def native_body(c):
    return (CheckDeckCondition(c.player_id,CONDITION,
        (InvokeBehavior('dsa.allocate',c.source_id,c.player_id),),()),)


def registry(current=CURRENT, watcher=None):
    raw=evidence();r=opening_registry()
    r.register_behavior('dsa.allocate',lambda c:allocation(c,r))
    r.register_behavior('dsa.native',native_body)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,
        cost=6,attack=6,health=6,battlecry='dsa.native',
        metadata=metadata(CardClass.NEUTRAL,rarity=Rarity.LEGENDARY,tribes=('elemental',))))
    r.register_behavior('dsa.nop',lambda c:())
    for letter,attack,health in (('a',2,3),('b',4,5),('c',0,7),('new',1,1)):
        r.register_card(CardDefinition('dsa.m.'+letter,'Finite stored-minion probe',
            CardType.MINION,attack=attack,health=health,metadata=metadata(tribes=())))
    for cost in (93,94,95):
        r.register_card(CardDefinition('dsa.original.'+str(cost),'Explicit starting cost operand',
            CardType.MINION,cost=cost,health=1,metadata=metadata()))
    for i in range(1,31):
        r.register_card(CardDefinition('dsa.filler.'+str(i),'Finite zero-cost spell',
            CardType.SPELL,on_play='dsa.nop',metadata=metadata()))
    for cid,cost in (('dsa.draw.filler',0),('dsa.current.spell',100)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,
            on_play='dsa.nop',metadata=metadata()))
    r.register_card(CardDefinition('dsa.current.weapon','Finite other-type probe',
        CardType.WEAPON,cost=100,attack=1,durability=1,metadata=metadata()))

    def first(c):return minion_references(c.state,r,c.player_id,SCOPE)[0]
    def native(c):return max(e.id for e in c.state.entities.values()
        if e.card_id==NATIVE and e.controller==c.player_id and e.zone==Zone.BOARD)
    def board_probe(c):return next(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id.startswith('dsa.m.'))
    tools={
        'destroy':lambda c:(Destroy(native(c),c.source_id),),
        'silence':lambda c:(Silence(native(c)),),
        'draw':lambda c:(Draw(c.player_id),),
        'silence.drawn':lambda c:(Silence(board_probe(c)),),
        'copy.current':lambda c:(CopyCard(first(c),c.player_id,mode='current'),),
        'copy.base':lambda c:(CopyCard(first(c),c.player_id,mode='base'),),
        'move':lambda c:(MoveCard(first(c),c.player_id,Zone.HAND),),
        'reset':lambda c:(MoveCard(first(c),c.player_id,Zone.HAND,reset=True),),
    }
    for name,body in tools.items():
        cid='dsa.tool.'+name;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def fail(c):raise RuntimeError('Deliberate allocation continuation failure')
    r.register_behavior('dsa.fail',fail)
    def reenter(c):
        card=c.state.entities[next(i for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id=='dsa.m.b')]
        return (MoveCard(CardReference.capture(card),c.player_id,Zone.DECK,'bottom'),)
    r.register_behavior('dsa.reenter',reenter)
    def pause(c):
        if c.event.player_id!=c.player_id:return ()
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=NATIVE:return ()
        if watcher=='after':
            if (c.state.entities[c.event.target_id].card_id!='dsa.m.a'
                    or dict(c.event.data).get('attack_delta',0)==0):return ()
            second=minion_references(c.state,r,c.player_id,SCOPE)[1]
            options=(ChoiceOption('go','Continue',()),
                ChoiceOption('fail','Fail',(InvokeBehavior('dsa.fail',c.source_id,c.player_id),)),
                ChoiceOption('replace','Move one original and add a new probe',(
                    MoveCard(second,c.player_id,Zone.HAND),
                    AddToDeck(c.player_id,'dsa.m.new','bottom'))),
                ChoiceOption('reenter','Leave and return the same physical probe',(
                    MoveCard(second,c.player_id,Zone.HAND),
                    InvokeBehavior('dsa.reenter',c.source_id,c.player_id))),
                ChoiceOption('source.leave','Remove the already accepted source',(
                    Destroy(source.id,c.source_id),)))
        else:
            options=(ChoiceOption('go','Continue',()),ChoiceOption('extra','Add a current probe',(
                AddToDeck(c.player_id,'dsa.m.new','bottom'),)))
        return (RequestChoice(c.player_id,options,c.source_id),)
    event='stored_card_buffed' if watcher=='after' else 'battlecry_started'
    r.register_behavior('dsa.watch',pause)
    r.register_card(CardDefinition('dsa.watch','Explicit diagnostic checkpoint',CardType.MINION,
        health=1,triggers=(TriggerSpec(event,'dsa.watch'),),metadata=metadata()))
    def prepare(c):
        original=c.state.players[c.player_id].original_deck
        return (ChangeManaCrystals(c.player_id,9),
            DestroyDeckMatching(c.player_id,count=40,reveal=False),
            AddToDeck(c.player_id,'dsa.draw.filler','bottom'),
            *(AddToDeck(c.player_id,cid,'bottom') for cid in current),
            AddToHand(c.player_id,NATIVE),AddToHand(c.player_id,'dsa.m.new'),
            *(AddToHand(c.player_id,cid) for cid in original if cid.startswith('dsa.tool.')),
            *(Summon(c.player_id,cid) for cid in original if cid=='dsa.watch'))
    r.register_behavior('dsa.prepare',prepare)
    r.register_card(CardDefinition('dsa.prep','Explicit experimental current-zone preparation',
        CardType.MINION,health=1,opening_hooks=(OpeningHook('after_mulligan','dsa.prepare'),),metadata=metadata()))
    return r


class DeckStatAllocationTests(unittest.TestCase):
    def match(self,current=CURRENT,*,total=100,other_total=100,first=1,tools=(),watcher=None):
        self.config=(tuple(current),watcher);r=registry(*self.config)
        def cards(total):
            prefix=('dsa.prep',NATIVE,'dsa.original.'+str(total-6))
            prefix+=tuple('dsa.tool.'+name for name in tools)
            if watcher:prefix+=('dsa.watch',)
            return prefix+tuple('dsa.filler.'+str(i) for i in range(1,31-len(prefix)))
        decks=tuple(DeckSpec('mage.hero','mage.power',CardClass.MAGE,cards(n)) for n in(total,other_total))
        g=Game.from_decks(MatchSetup(decks,policy(r),'coin',87,first),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;self.assertEqual(q.purpose,ChoicePurpose.MULLIGAN)
            g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def source(self,g,player=1):
        return max(e.id for e in g.state.entities.values() if e.card_id==NATIVE and e.controller==player)
    def play(self,g,player=1):return g.apply(PlayCard(player,self.source(g,player)))
    def targets(self,g,player=1):
        return tuple(g.state.entities[i] for i in g.state.players[player].deck if g.state.entities[i].kind==CardType.MINION)
    def baseline(self,g,player=1):return {e.id:(e.attack,e.max_health) for e in self.targets(g,player)}
    def delta(self,g,before):
        return tuple((g.state.entities[i].attack-a,g.state.entities[i].max_health-h) for i,(a,h) in before.items())
    def choose(self,g,option='go'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def tool(self,g,name,player=1):
        cid='dsa.tool.'+name;i=max(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(player,i))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry(*self.config))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        return restored

    def test_complete_native_raw_metadata_and_no_new_runtime_effect(self):
        raw=evidence();card=registry().card(NATIVE)
        original=next(r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes()) if r['id']==NATIVE)
        self.assertEqual(raw,original)
        self.assertEqual((card.cost,card.attack,card.health),(6,6,6))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.tribes),
            ((CardClass.NEUTRAL,),Rarity.LEGENDARY,('elemental',)))
        self.assertEqual(card.battlecry,'dsa.native');self.assertIsNone(card.targeting)

    def test_three_minions_receive_observed_seventeen_seventeen_sixteen_without_rng(self):
        g=self.match();before=self.baseline(g);rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)))
        self.assertEqual(sum(a+h for a,h in self.delta(g,before)),100)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual(len([e for e in g.events if e.kind=='mana_spent' and e.source_id==self.source(g)]),1)

    def test_even_divisible_pools_keep_fifty_attack_and_fifty_health(self):
        for count in (1,2,5):
            with self.subTest(count=count):
                g=self.match(('dsa.m.a',)*count);before=self.baseline(g);self.play(g)
                self.assertEqual(self.delta(g,before),((50//count,50//count),)*count)

    def test_duplicate_card_ids_are_separate_physical_targets_and_remainder_weights(self):
        g=self.match(('dsa.m.a',)*3);before=self.baseline(g);self.play(g)
        self.assertEqual(len(before),3);self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)))
        attachments=[a.id for e in self.targets(g) for a in e.enchantments]
        self.assertEqual(len(attachments),len(set(attachments)));self.assertEqual(len(attachments),6)

    def test_stored_attack_then_health_use_separate_ordinary_attachments(self):
        g=self.match();before=self.baseline(g);self.play(g);source=self.source(g)
        events=[e for e in g.events if e.kind=='stored_card_buffed' and e.source_id==source]
        self.assertEqual([e.target_id for e in events],[i for i in before for _ in range(2)])
        self.assertEqual([(dict(e.data)['attack_delta'],dict(e.data)['health_delta']) for e in events],
            [(17,0),(0,17),(17,0),(0,17),(16,0),(0,16)])
        for entity,amount in zip(self.targets(g),(17,17,16)):
            self.assertEqual([(a.attack,a.health,a.source_id) for a in entity.enchantments],
                [(amount,0,source),(0,amount,source)])

    def test_only_current_deck_minions_change_ignoring_other_types_hand_and_source(self):
        g=self.match(('dsa.current.spell','dsa.m.a','dsa.current.weapon','dsa.m.b'))
        before=self.baseline(g);hand={i:(g.state.entities[i].attack,g.state.entities[i].max_health)
            for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION}
        self.play(g);self.assertEqual(self.delta(g,before),((25,25),(25,25)))
        for i,stats in hand.items():self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health),stats)
        for i in g.state.players[1].deck:
            if g.state.entities[i].kind!=CardType.MINION:self.assertFalse(g.state.entities[i].enchantments)

    def test_ninety_nine_and_one_hundred_one_starting_totals_take_empty_branch(self):
        for total in (99,101):
            with self.subTest(total=total):
                g=self.match(total=total);before=self.baseline(g);rng=g._rng.getstate();self.play(g)
                self.assertEqual(self.delta(g,before),((0,0),)*3);self.assertEqual(g._rng.getstate(),rng)
                self.assertEqual(g.state.entities[self.source(g)].zone,Zone.BOARD)

    def test_actual_second_controller_uses_own_starting_facts_and_current_targets(self):
        g=self.match(total=99,other_total=100,first=2);own=self.baseline(g,2);other=self.baseline(g,1)
        self.play(g,2);self.assertEqual(self.delta(g,own),((17,17),(17,17),(16,16)))
        self.assertEqual(self.delta(g,other),((0,0),)*3);self.assertEqual(g.state.players[2].mana,4)

    def test_empty_current_minion_pool_finishes_without_division_or_rng(self):
        g=self.match(('dsa.current.spell','dsa.current.weapon'));rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.targets(g),());self.assertEqual(g._rng.getstate(),rng)
        self.assertFalse([e for e in g.events if e.kind=='stored_card_buffed' and e.source_id==self.source(g)])

    def test_before_acceptance_wait_uses_new_current_pool_with_original_starting_gate(self):
        g=self.match(watcher='before');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        restored=self.portable(g);self.choose(g,'extra');self.choose(restored,'extra')
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual([(a.attack,a.health) for e in self.targets(g) for a in e.enchantments],
            [(13,0),(0,13),(13,0),(0,13),(12,0),(0,12),(12,0),(0,12)])
        self.assertEqual(g.state.players[1].mana,4)

    def test_mid_allocation_wait_restores_clone_and_replay_with_fixed_remaining_budget(self):
        g=self.match(watcher='after');before=self.baseline(g);rng=g._rng.getstate();self.play(g)
        self.assertEqual(self.delta(g,before),((17,0),(0,0),(0,0)))
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)));self.portable(g)

    def test_accepted_departed_target_is_skipped_without_new_target_or_redistribution(self):
        g=self.match(watcher='after');before=self.baseline(g);self.play(g);self.choose(g,'replace')
        self.assertEqual(self.delta(g,before),((17,17),(0,0),(16,16)))
        newer=[e for e in self.targets(g) if e.id not in before]
        self.assertEqual(len(newer),1);self.assertFalse(newer[0].enchantments)
        self.assertEqual(len([e for e in g.events if e.kind=='zone_target_skipped']),2)

    def test_leave_and_reenter_same_physical_id_fails_old_zone_epoch_guard(self):
        g=self.match(watcher='after');before=self.baseline(g);second=tuple(before)[1]
        epoch=g.state.entities[second].zone_epoch;self.play(g);self.choose(g,'reenter')
        self.assertEqual(g.state.entities[second].zone,Zone.DECK)
        self.assertEqual(g.state.entities[second].zone_epoch,epoch+2)
        self.assertEqual(self.delta(g,before),((17,17),(0,0),(16,16)))

    def test_removing_accepted_source_does_not_cancel_already_captured_buffs(self):
        g=self.match(watcher='after');before=self.baseline(g);self.play(g);self.choose(g,'source.leave')
        self.assertEqual(g.state.entities[self.source(g)].zone,Zone.GRAVEYARD)
        self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)))

    def test_source_silence_and_death_after_resolution_do_not_revoke_stored_growth(self):
        for name in('silence','destroy'):
            with self.subTest(name=name):
                g=self.match(tools=(name,));before=self.baseline(g);self.play(g);self.tool(g,name)
                self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)))

    def test_current_and_base_copies_keep_independent_material_and_attachments(self):
        g=self.match(tools=('copy.current','copy.base'));self.play(g);original=self.targets(g)[0]
        self.tool(g,'copy.current');current=g.state.entities[g.state.players[1].hand[-1]]
        self.tool(g,'copy.base');base=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((current.attack,current.max_health),(original.attack,original.max_health))
        self.assertEqual((base.attack,base.max_health),(2,3));self.assertFalse(base.enchantments)
        self.assertTrue(set(a.id for a in current.enchantments).isdisjoint(a.id for a in original.enchantments))

    def test_movement_preserves_growth_and_explicit_reset_clears_it(self):
        for name,stats in(('move',(19,20)),('reset',(2,3))):
            with self.subTest(name=name):
                g=self.match(tools=(name,));self.play(g);original=self.targets(g)[0]
                self.tool(g,name);original=g.state.entities[original.id]
                self.assertEqual(original.zone,Zone.HAND)
                self.assertEqual((original.attack,original.max_health),stats)

    def test_real_draw_and_play_inherit_growth_then_silence_removes_it(self):
        g=self.match(tools=('draw','silence.drawn'));self.play(g);original=self.targets(g)[0];self.tool(g,'draw')
        original=g.state.entities[original.id]
        self.assertEqual(original.zone,Zone.HAND);g.apply(PlayCard(1,original.id))
        original=g.state.entities[original.id]
        self.assertEqual((original.attack,original.max_health,original.health),(19,20,20))
        self.tool(g,'silence.drawn')
        original=g.state.entities[original.id]
        self.assertEqual((original.attack,original.max_health,original.health),(2,3,3))
        self.assertFalse(original.enchantments)

    def test_failed_choice_rolls_back_to_same_paid_waiting_acceptance(self):
        g=self.match(watcher='after');before=self.baseline(g);self.play(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].mana,4)
        self.choose(g);self.assertEqual(self.delta(g,before),((17,17),(17,17),(16,16)))

    def test_unknown_starting_facts_are_rejected_without_partial_resolution(self):
        self.config=(CURRENT,None);r=registry();g=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(NATIVE,),deck=CURRENT,mana=10,max_mana=10),
            PlayerSetup('mage.hero'))),r);saved=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_private_deck_budget_and_waiting_targets_do_not_leak_to_players(self):
        g=self.match(watcher='after');self.play(g);saved=g.snapshot()
        public=json.dumps(g.observe(2))+json.dumps(g.player_events(2))+json.dumps(g.for_player(2).legal_actions())
        for cid in CURRENT:self.assertNotIn(cid,public)
        for key in('rng_state','original_deck','enchantments','resolution_frame','zone_epoch'):
            self.assertNotIn('"'+key+'"',public)
        own=json.dumps(g.observe(1));self.assertNotIn('"enchantments"',own)
        self.assertNotIn('"resolution_frame"',own);self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
