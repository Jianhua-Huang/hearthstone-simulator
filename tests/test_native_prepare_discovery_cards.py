"""Wanted Poster uses the original selected card and ordinary Prepare lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_prepare_discovery_cards import (
    BATCH_HASH, GRANT, POLICY, POOL_ID, QUERY, WANTED_POSTER, load_batch,
    register_native_prepare_discovery_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, HandActionSpec, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity,
    Registry, Scenario, SelectChoice, UseHandAction, Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_actions import PREPARE, specifications
from hs_sim.engine.model import AbilityInstance, LimitedTriggerSpec
from hs_sim.engine.pools import (DiscoverFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

P = 'k186.'
HERO, FILLER, A, B, C, D, LOW, OTHER, HIDDEN, UNKNOWN = (
    P+s for s in ('hero','filler','a','b','c','d','low','other','hidden','unknown'))
MEMBERS = (A, B, C, D, LOW, OTHER, HIDDEN)
MINIONS = (A, B, C, D)
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON)
CTX = GenerationContext('k186-explicit-bounded-minions', 'experimental')


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True, role='writer'):
    r = Registry('k186-selected-prepare-v1')
    register_native_prepare_discovery_cards(r)
    for n, cid in enumerate(MEMBERS):
        metadata = (replace(META, classes=(CardClass.MAGE,)) if cid == B else
                    replace(META, classes=(CardClass.WARRIOR,)) if cid == OTHER else
                    replace(META, collectible=False) if cid == HIDDEN else META)
        cost = 4 if cid == LOW else 5+n
        card = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=5,
            metadata=metadata, hand_actions=(PREPARE,) if cid == C else ())
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_card(CardDefinition(FILLER, FILLER, CardType.MINION, cost=1, attack=1, health=2))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 7, META,
            battlecry=False, deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k186-bounded-complete-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c): raise ResolutionError('K186 deliberate reaction failure')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'auto', lambda c: (AddToHand(c.player_id,FILLER,c.source_id),
        CastSpell(c.player_id,WANTED_POSTER,c.source_id,choices='player')))
    r.register_card(CardDefinition(P+'auto', 'Automatic Wanted Poster', CardType.SPELL, on_play=P+'auto'))
    def operation(c, op):
        entity = next(e for e in c.state.entities.values() if e.card_id in MINIONS and
            e.zone in (Zone.HAND, Zone.BOARD) and any(a.kind=='prepare' for a in e.abilities))
        if op in ('copy','base','shuffle','transfer'):
            reference = CardReference.capture(entity)
        if op in ('copy','base'):
            return (CopyCard(reference,c.player_id,Zone.HAND,
                mode='current' if op=='copy' else 'base',source_id=c.source_id),)
        if op == 'shuffle':
            return (MoveCard(reference,c.player_id,Zone.DECK,reset=True,source_id=c.source_id),)
        if op == 'transfer': return (MoveCard(reference,2,Zone.HAND,source_id=c.source_id),)
        if op == 'bounce': return (ReturnToHand(entity.id),)
        if op == 'silence': return (Silence(entity.id),)
        return (Transform(entity.id,FILLER),)
    for op in ('copy','base','shuffle','transfer','bounce','silence','transform'):
        r.register_behavior(P+op,lambda c, op=op: operation(c,op))
        r.register_card(CardDefinition(P+op,op,CardType.SPELL,on_play=P+op))
    r.register_behavior(P+'bad-create',lambda c:(AddToHand(c.player_id,WANTED_POSTER,c.source_id,
        minion_grant=GRANT),))
    r.register_card(CardDefinition(P+'bad-create','Invalid grant carrier',CardType.SPELL,on_play=P+'bad-create'))
    kwargs = {}
    if mode:
        def eligible(c):
            return c.event.player_id==c.player_id and c.event.target_id is not None and (
                c.state.entities[c.event.target_id].card_id in MINIONS)
        def observer(c):
            if mode == 'inspect':
                complete = any(a.kind=='prepare' for a in c.state.entities[c.event.target_id].abilities)
                return (GainArmor(c.player_id,11 if complete else 1),)
            if mode.endswith('fail'): return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible)
        r.register_behavior(P+'observe',observer)
        kwargs['limited_triggers'] = (LimitedTriggerSpec(
            'card_prepared' if mode.startswith('prepare-') else 'card_created',
            P+'observe',condition_id=P+'eligible'),)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,
        metadata=CardMetadata(False,(CardClass.MAGE,),None),**kwargs))
    r.validate()
    return r


class NativePrepareDiscoveryTests(unittest.TestCase):
    def game(self, members=MEMBERS, mode=None, pool=True, hand=(WANTED_POSTER,), mana=20):
        self.config = members, mode, pool
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,deck=(FILLER,)*8,mana=mana,max_mana=20,mana_cap=20),
            PlayerSetup(HERO,deck=(FILLER,)*8,mana=10,max_mana=10)),seed=186,
            generation_context=CTX),registry(*self.config))

    def play(self,g,cid=WANTED_POSTER):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,source)); return source

    def pick(self,g,cid=None):
        q = g.state.pending_choice
        option = next(o for o in q.options if cid is None or o.card_id==cid)
        prior = set(g.state.entities)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
        created = [i for i in set(g.state.entities)-prior if g.state.entities[i].card_id==option.card_id]
        self.assertEqual(len(created),1)
        return created[0]

    def discover(self,g,cid=None):
        self.play(g); return self.pick(g,cid)

    def grants(self,g,entity_id):
        return tuple(a for a in g.state.entities[entity_id].abilities if a.kind=='prepare')

    def use(self,g,entity_id): return g.apply(UseHandAction(g.state.active_player,entity_id,'prepare'))

    def portable(self,g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = registry.__wrapped__(*self.config,role='reader')
        self.assertIsNot(reader,g.registry)
        other = Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        return other

    def test_complete_original_source_neutral_spell_query_and_central_assembly(self):
        from hs_sim.cards.constructed import build_registry
        data=load_batch(); raw=data['cards'][0]['record']; central=build_registry()
        self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((data['policy'],raw['dbf_id'],raw['cost'],raw['tags']['CLASS']),
            (POLICY,129888,2,12))
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual((QUERY.min_cost,QUERY.class_mode,QUERY.collectible),(5,'current',True))
        self.assertEqual((central.card(WANTED_POSTER).cost,central.card(WANTED_POSTER).metadata.classes),
            (2,(CardClass.NEUTRAL,)))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_original_offer_filters_printed_cost_class_and_collectibility(self):
        g=self.game();self.play(g);q=g.state.pending_choice
        self.assertEqual(len(q.options),3)
        self.assertTrue({o.card_id for o in q.options} <= set(MINIONS))
        self.assertTrue(all(o.card_id not in (LOW,OTHER,HIDDEN) for o in q.options))
        self.portable(g)

    def test_only_chosen_physical_card_has_prepare_before_first_notification(self):
        g=self.game(mode='inspect',hand=(WANTED_POSTER,A))
        old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==A)
        source=self.play(g);selected=self.pick(g)
        self.assertEqual(len(self.grants(g,selected)),1)
        self.assertEqual(self.grants(g,selected)[0].source_id,source)
        self.assertFalse(self.grants(g,old))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,11)
        self.assertIsNone(g.state.entities[selected].preparation)
        self.assertEqual(g.quote_cost(selected).amount,g.registry.card(g.state.entities[selected].card_id).cost)
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.portable(g)

    def test_prepare_uses_native_investment_discount_and_preserves_entity_slot_rng(self):
        g=self.game(mana=5);selected=self.discover(g)
        before=g.state.entities[selected];hand=tuple(g.state.players[1].hand);rng=g.snapshot()['rng_state']
        cost=g.quote_cost(selected).amount;amount=g.quote_hand_action(selected,'prepare').amount
        self.assertEqual(amount,3)
        self.use(g,selected);after=g.state.entities[selected]
        self.assertEqual((g.state.players[1].mana,g.quote_cost(selected).amount),(0,cost-amount-1))
        self.assertEqual((after.id,after.zone_epoch),(before.id,before.zone_epoch))
        self.assertEqual(tuple(g.state.players[1].hand),hand)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        self.portable(g)

    def test_once_and_current_turn_lock_then_normal_play_on_later_turn(self):
        g=self.game(mana=5);selected=self.discover(g);self.use(g,selected)
        before=g.snapshot()
        for action in (UseHandAction(1,selected,'prepare'),PlayCard(1,selected)):
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        with self.assertRaises(IllegalAction):self.use(g,selected)
        g.apply(PlayCard(1,selected));self.assertIn(selected,g.state.players[1].board)
        self.portable(g)

    def test_native_printed_prepare_is_not_duplicated_by_grant(self):
        g=self.game(members=(C,));selected=self.discover(g)
        specs=specifications(g.registry,g.state.entities[selected])
        self.assertEqual(specs,(PREPARE,))
        self.assertEqual(len([a for a in g.legal_actions() if isinstance(a,UseHandAction)]),1)
        self.use(g,selected);self.portable(g)

    def test_player_action_view_command_and_opponent_information_boundary(self):
        g=self.game(mana=5);selected=self.discover(g)
        own=next(x for x in g.observe(1)['players'][0]['hand'] if x['card_id']==g.state.entities[selected].card_id)
        self.assertEqual(own['hand_actions'][0]['kind'],'prepare')
        port=g.for_player(1);view=port.observe()
        command=next(a for a in port.legal_actions()['actions'] if a['type']=='use_hand_action')
        result=port.submit({'revision':view['revision'],'action':command})
        self.assertTrue(result['accepted'])
        enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(set(enemy),{'ref','card_id'});self.assertIsNone(enemy['card_id'])
        self.assertNotIn(g.state.entities[selected].card_id,json.dumps(g.observe(2)))
        event=next(e for e in g.player_events(2) if e['kind']=='card_prepared')
        self.assertEqual(event['amount'],3);self.assertIsNone(event['source']);self.assertIsNone(event['target'])
        self.portable(g)

    def test_zero_remaining_mana_does_not_spend_or_consume_granted_prepare(self):
        g=self.game(mana=2);selected=self.discover(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g,selected)
        self.assertEqual(g.snapshot(),before)
        self.assertIsNone(g.state.entities[selected].preparation)
        self.assertEqual(len(self.grants(g,selected)),1)

    def test_unknown_qualified_candidate_fails_before_rng_or_payment_commit(self):
        g=self.game(members=(A,B,UNKNOWN));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_absent_formal_pool_fails_explicitly_and_rolls_back(self):
        g=self.game(pool=False);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_eligible_pool_creates_no_card_or_rng_draw(self):
        g=self.game(members=(LOW,OTHER,HIDDEN));before=g.snapshot()['rng_state'];count=len(g.state.entities)
        self.play(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.entities),count)
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(any(a.kind=='prepare' for e in g.state.entities.values() for a in e.abilities))

    def test_current_hand_copy_retains_grant_and_remaps_prepared_discount(self):
        g=self.game(members=(A,),hand=(WANTED_POSTER,P+'copy'),mana=5)
        selected=self.discover(g);self.use(g,selected);self.play(g,P+'copy')
        twins=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==A]
        self.assertEqual(len(twins),2)
        first,second=(g.state.entities[i] for i in twins)
        self.assertNotEqual(first.preparation.cost_id,second.preparation.cost_id)
        self.assertNotEqual(self.grants(g,twins[0])[0].id,self.grants(g,twins[1])[0].id)
        self.assertEqual(first.preparation.mana_spent,second.preparation.mana_spent)
        for i in twins:
            self.assertEqual(g.quote_cost(i).amount,1)
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,i))
        self.portable(g)

    def test_base_copy_does_not_inherit_a_physical_prepare_grant(self):
        g=self.game(members=(A,),hand=(WANTED_POSTER,P+'base'));selected=self.discover(g)
        self.play(g,P+'base')
        other=next(i for i in g.state.players[1].hand if i!=selected)
        self.assertFalse(self.grants(g,other))
        self.assertEqual(specifications(g.registry,g.state.entities[other]),())
        self.assertEqual(len(self.grants(g,selected)),1);self.portable(g)

    def test_reset_to_deck_clears_grant_and_preparation_using_existing_lifecycle(self):
        g=self.game(members=(A,),hand=(WANTED_POSTER,P+'shuffle'),mana=5)
        selected=self.discover(g);self.use(g,selected);self.play(g,P+'shuffle')
        self.assertIn(selected,g.state.players[1].deck)
        self.assertFalse(self.grants(g,selected));self.assertIsNone(g.state.entities[selected].preparation)
        entity=g.state.entities[selected]
        self.assertEqual((entity.base_cost,entity.enchantments),(5,[]));self.portable(g)

    def test_hand_transfer_preserves_independent_grant_for_new_controller(self):
        g=self.game(members=(A,),hand=(WANTED_POSTER,P+'transfer'));selected=self.discover(g)
        self.play(g,P+'transfer');self.assertIn(selected,g.state.players[2].hand)
        g.apply(EndTurn(1));self.use(g,selected)
        self.assertIsNotNone(g.state.entities[selected].preparation);self.portable(g)

    def test_bounce_silence_and_transform_retire_grant_without_reapplying_definition(self):
        for op in ('bounce','silence','transform'):
            with self.subTest(op=op):
                g=self.game(members=(A,),hand=(WANTED_POSTER,P+op));selected=self.discover(g)
                g.apply(PlayCard(1,selected));self.play(g,P+op)
                self.assertFalse(self.grants(g,selected))
                if op=='bounce':
                    self.assertIn(selected,g.state.players[1].hand)
                    self.assertEqual(specifications(g.registry,g.state.entities[selected]),())
                self.portable(g)

    def test_first_creation_wait_roundtrips_original_grant_and_delivery_once(self):
        g=self.game(mode='wait');self.play(g);self.portable(g);selected=self.pick(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.grants(g,selected)),1)
        restored=self.portable(g)
        for work in (g,restored):
            q=work.state.pending_choice;work.apply(SelectChoice(q.player_id,q.id,('ok',)))
            self.assertIsNone(work.state.pending_choice)
            self.assertEqual(len(self.grants(work,selected)),1)
            self.assertEqual(work.state.players[1].hand.count(selected),1)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_failed_creation_reaction_rolls_back_grant_entity_and_original_choice(self):
        g=self.game(mode='fail');self.play(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id,)))
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_prepare_reaction_wait_restores_spend_once_and_failure_rolls_back(self):
        g=self.game(mode='prepare-wait',mana=5);selected=self.discover(g);self.use(g,selected)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        prior=restored.snapshot();q=restored.state.pending_choice
        with self.assertRaises(ResolutionError):restored.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(restored.snapshot(),prior)
        restored.apply(SelectChoice(1,q.id,('ok',)))
        self.assertEqual(restored.state.players[1].mana,0)
        self.assertEqual(restored.state.entities[selected].preparation.mana_spent,3)
        self.portable(restored)

    def test_automatic_cast_overflow_keeps_complete_burned_material(self):
        g=self.game(mode='inspect',hand=(P+'auto',)+(FILLER,)*9)
        self.play(g,P+'auto');self.assertEqual(len(g.state.players[1].hand),10)
        selected=self.pick(g)
        self.assertNotIn(selected,g.state.players[1].hand)
        self.assertEqual(len(self.grants(g,selected)),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,11)
        self.portable(g)

    def test_prepare_grant_cannot_be_mixed_into_an_effect_program_or_nonminion(self):
        for values in ({'attack':1},{'health':1},{'keywords':(Keyword.TAUNT,)},{'special':'unknown'}):
            with self.subTest(values=values),self.assertRaises(ValueError):replace(GRANT,**values)
        for changes in ({'source_id':None},{'behavior_id':'anything'},{'origin':'printed'},
                        {'remove_on_silence':False},{'expires_turn':3},{'consumed':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                AbilityInstance(1,'prepare',**dict({'source_id':2},**changes))
        g=self.game(hand=(P+'bad-create',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'bad-create')
        self.assertEqual(g.snapshot(),before)

    def test_discovery_recipe_and_serialized_grant_reject_invalid_shapes(self):
        request=DiscoverFromPool(1,POOL_ID,QUERY,source_id=1,minion_grant=GRANT)
        for values in ({'destination':'deck'},{'count':2},{'source_id':None},{'discoveries':2}):
            with self.subTest(values=values),self.assertRaises(ValueError):replace(request,**values)
        g=self.game(members=(A,));selected=self.discover(g);saved=g.snapshot()
        for field,value in (('behavior_id','anything'),('origin','printed'),('source_id',None)):
            forged=deepcopy(saved)
            rows=forged['state']['entities'];rows=rows.values() if isinstance(rows,dict) else rows
            row=next(x for x in rows if x['id']==selected)
            ability=next(x for x in row['abilities'] if x['kind']=='prepare');ability[field]=value
            forged['state_hash']=canonical_hash(forged['state'])
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(forged,g.registry)
        old=deepcopy(saved);old['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,g.registry)


if __name__ == '__main__': unittest.main()
