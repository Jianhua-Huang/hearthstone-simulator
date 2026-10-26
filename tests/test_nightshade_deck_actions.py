"""Actual Nightshade Bud uses original physical cards without a hand intermediate."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, FILLER
from hs_sim.cards.nightshade_deck_actions import ROOT, MINION, SPELL, COMBINED, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.deck_discovery_actions import DiscoverDeckCardAction
from hs_sim.engine.discovery_delivery import original_recipient, validate_recipe
from hs_sim.engine.effects import AddToHand, ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyStoredCard, ModifyStoredCost
from tools import card_batch as batch

S = 'k553.'
WATCH, WAIT_SPELL, FAIL_SPELL, CRY = (S+x for x in ('watch','wait_spell','fail_spell','cry'))
SAFE = 'CORE_EX1_169'
FANDRAL = 'CORE_OG_044'
CTX = GenerationContext('k553-native-nightshade-test', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.spells','one-native-nightshade-test-v1',
        CTX.target_id,CTX.mode,(PoolMember(ROOT),),complete=True))

    def fail(c):raise ResolutionError('k553 original delivery failure')
    def seed(c):
        return tuple(effect for i in c.state.players[c.player_id].deck
            for e in (c.state.entities[i],)
            for effect in ((BuffStoredCard(CardReference.capture(e),2,3,c.source_id),
                ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=1),c.source_id))
                if e.kind==CardType.MINION else
                (ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=9),c.source_id),)))
    def wait(c):
        return (RequestChoice(3-c.player_id if c.source.card_id==WAIT_SPELL else c.player_id,(
            ChoiceOption('continue','Continue',(GainArmor(c.player_id,2),)),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
    def observe(c):
        if mode=='full_hand' and c.event.kind=='card_committed':
            source=c.state.entities.get(c.event.source_id)
            return (AddToHand(c.player_id,FILLER,c.source_id),)if source is not None and source.card_id==ROOT else ()
        if c.event.kind!='minion_summoned':return ()
        roots=c.state.card_summon_history
        if not roots or roots[-1].request.cause.cast_card_id!=ROOT:return ()
        if mode=='minion_fault':return (InvokeBehavior(S+'fail',c.source_id,c.player_id),)
        if mode=='minion_wait':return wait(c)
        if mode=='combined_rewrite':
            return (*tuple(DestroyStoredCard(CardReference.capture(c.state.entities[i]),c.source_id)
                for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.SPELL),
                AddToDeck(c.player_id,'CORE_CS2_029',position='bottom',source_id=c.source_id))
        return ()

    for name,body in (('fail',fail),('seed',seed),('wait_spell',wait),
            ('fail_spell',lambda c:(InvokeBehavior(S+'fail',c.source_id,c.player_id),)),
            ('cry',lambda c:(GainArmor(c.player_id,99),))):
        r.register_behavior(S+name,body)
        if name!='cry':r.register_card(CardDefinition(S+name,name,CardType.SPELL,
            cost=4 if name=='wait_spell'else 0,on_play=S+name))
    r.register_card(CardDefinition(CRY,'Diagnostic battlecry',CardType.MINION,cost=2,
        attack=3,health=4,battlecry=S+'cry'))
    r.register_card(CardDefinition(S+'target_spell','Diagnostic target',CardType.SPELL,
        requires_target=True,target_rule='m1.enemy_minion',on_play=S+'cry'))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Entry observer',CardType.MINION,health=30,
        triggers=tuple(TriggerSpec(event,S+'observe')for event in ('minion_summoned','card_committed'))))
    r.validate();return replace(fmt,context=CTX)


def wires(value):
    if type(value)is dict:
        yield value
        for row in value.values():yield from wires(row)
    elif type(value)is list:
        for row in value:yield from wires(row)


class NightshadeDeckActionTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,*,hand=(ROOT,),deck=(),board=(),mode='normal',seed=1):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('HERO_08')),seed=seed,generation_context=CTX),fmt.registry)

    def root(self,game,branch):
        source=self.entity(game,ROOT).id
        game.apply(PlayCard(1,source,branch_id=branch));return source

    def pick_card(self,game,cid):
        option=next(o for o in game.state.pending_choice.options if o.card_id==cid)
        self.choose(game,option.id)

    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_full_raw_parent_copy_association_and_choice_only_source_faces(self):
        data=load_batch();source={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        for key in ('cards','choices','evidence_only'):
            for row in data[key]:self.assertEqual(row['record'],source[row['record']['id']])
        for observation in data['official_faces']:
            batch.check_face(source[observation['card_id']],observation['face'],observation['locale'])
        r=fixture().registry
        self.assertEqual(r.card(ROOT).metadata.deck_identity,'REV_311')
        self.assertEqual([b.id for b in r.card(ROOT).choose_one.branches],[MINION,SPELL])
        self.assertTrue(all(r.card(cid).choice_only and cid not in r.pool_cards for cid in (MINION,SPELL)))
        self.assertEqual(set(data['missing_primary_ids']),{ROOT,MINION,SPELL})
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_minion_discovery_moves_original_modified_entity_and_preserves_unselected_spell(self):
        game=self.game(hand=(S+'seed',ROOT),deck=(FILLER,SAFE));self.play(game,S+'seed')
        selected=next(i for i in game.state.players[1].deck if game.state.entities[i].card_id==FILLER)
        kept=next(i for i in game.state.players[1].deck if game.state.entities[i].card_id==SAFE)
        source=self.root(game,MINION);option=game.state.pending_choice.options[0]
        self.assertEqual((option.preview.cost,option.preview.attack,option.preview.health),(1,7,8))
        self.assertNotIn(FILLER,json.dumps(game.for_player(2).observe()))
        restored=self.portable(game);self.pick_card(restored,FILLER);self.pick_card(game,FILLER)
        self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual(game.state.players[1].board,[selected]);self.assertEqual(game.state.players[1].deck,[kept])
        body=game.state.entities[selected];self.assertEqual((body.attack,body.health),(7,8))
        self.assertEqual(game.state.players[1].mana,2);self.assertFalse(game.state.draw_history)
        root=game.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.source.entity_id,root.request.cause.cast_card_id),(source,ROOT))
        event=next(e for e in game.events if e.kind=='card_discovered')
        self.assertEqual(original_recipient(game.state,event).entity_id,selected);self.portable(game)

    def test_original_deck_spell_is_cast_free_and_has_actual_physical_discovery_recipient(self):
        game=self.game(hand=(S+'seed',ROOT),deck=(SAFE,FILLER));self.play(game,S+'seed')
        selected=next(i for i in game.state.players[1].deck if game.state.entities[i].card_id==SAFE)
        source=self.root(game,SPELL)
        self.assertEqual(game.state.pending_choice.options[0].preview.cost,9)
        self.pick_card(game,SAFE)
        cast=game.state.cast_history[-1]
        self.assertEqual((cast.source_id,cast.card_id,cast.caster_id,cast.from_zone),(selected,SAFE,source,Zone.DECK))
        self.assertEqual(game.state.entities[selected].zone,Zone.GRAVEYARD)
        self.assertEqual((game.state.players[1].mana,game.state.players[1].temporary_mana),(3,1))
        self.assertFalse(game.state.draw_history)
        event=next(e for e in game.events if e.kind=='card_discovered')
        self.assertEqual(original_recipient(game.state,event).entity_id,selected);self.portable(game)

    def test_discovered_minion_does_not_execute_its_battlecry(self):
        game=self.game(deck=(CRY,));self.root(game,MINION);self.pick_card(game,CRY)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,0)
        self.assertEqual(len(game.state.players[1].board),1)

    def test_both_real_branches_deliver_directly_while_hand_is_full(self):
        for branch,cid in ((MINION,FILLER),(SPELL,SAFE)):
            with self.subTest(branch=branch):
                game=self.game(hand=(ROOT,)+(FILLER,)*9,deck=(cid,),board=(WATCH,),mode='full_hand')
                selected=game.state.players[1].deck[0];self.root(game,branch)
                self.assertEqual(len(game.state.players[1].hand),10)
                self.pick_card(game,cid)
                self.assertEqual(len(game.state.players[1].hand),10)
                self.assertEqual(game.state.entities[selected].zone,Zone.BOARD if branch==MINION else Zone.GRAVEYARD)
                self.assertFalse(any(e.kind=='card_burned'for e in game.events))

    def test_full_board_keeps_the_selected_minion_in_deck_and_records_failed_entry(self):
        game=self.game(deck=(FILLER,),board=(FILLER,)*7);selected=game.state.players[1].deck[0]
        self.root(game,MINION);self.pick_card(game,FILLER)
        self.assertEqual(game.state.players[1].deck,[selected]);self.assertEqual(len(game.state.players[1].board),7)
        self.assertFalse(game.state.successful_summon_history)
        event=next(e for e in game.events if e.kind=='card_discovered')
        self.assertIsNone(original_recipient(game.state,event));self.portable(game)

    def test_empty_kind_finishes_paid_root_without_choice_or_randomness(self):
        for branch,deck in ((MINION,(SAFE,)),(SPELL,(FILLER,))):
            with self.subTest(branch=branch):
                game=self.game(deck=deck);rng=game.snapshot()['rng_state'];original=tuple(game.state.players[1].deck)
                self.root(game,branch)
                self.assertIsNone(game.state.pending_choice);self.assertEqual(game.snapshot()['rng_state'],rng)
                self.assertEqual(tuple(game.state.players[1].deck),original);self.assertEqual(game.state.players[1].mana,2)

    def test_real_fandral_combined_queries_spells_after_completed_minion_reactions(self):
        game=self.game(deck=(FILLER,SAFE),board=(FANDRAL,WATCH),mode='combined_rewrite')
        self.root(game,COMBINED);self.assertEqual([o.card_id for o in game.state.pending_choice.options],[FILLER])
        self.pick_card(game,FILLER)
        self.assertEqual([o.card_id for o in game.state.pending_choice.options],['CORE_CS2_029'])
        restored=self.portable(game);self.pick_card(restored,'CORE_CS2_029');self.pick_card(game,'CORE_CS2_029')
        self.assertEqual(restored.snapshot(),game.snapshot());self.assertEqual(len(game.state.card_discovery_history),2)
        self.assertEqual([c.card_id for c in game.state.cast_history],[ROOT,'CORE_CS2_029'])
        self.portable(game)

    def test_recruited_body_wait_restores_owed_discovery_and_rejects_failed_branch(self):
        game=self.game(deck=(FILLER,),board=(WATCH,),mode='minion_wait')
        self.root(game,MINION);self.pick_card(game,FILLER)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual(sum(e.kind=='card_discovered'for e in game.events),1);self.portable(game)

    def test_selected_spell_wait_restores_original_cast_and_physical_discovery_completion(self):
        game=self.game(deck=(WAIT_SPELL,));selected=game.state.players[1].deck[0]
        self.root(game,SPELL);self.pick_card(game,WAIT_SPELL)
        self.assertEqual(game.state.pending_choice.player_id,2)
        self.assertEqual(game.state.cast_history[-1].source_id,selected)
        self.assertFalse(game.state.cast_history[-1].completed)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,2)
        event=next(e for e in game.events if e.kind=='card_discovered')
        self.assertEqual(original_recipient(game.state,event).entity_id,selected);self.portable(game)

    def test_delivery_failure_preserves_already_paid_original_discovery_boundary(self):
        for branch,cid,mode,board in ((MINION,FILLER,'minion_fault',(WATCH,)),(SPELL,FAIL_SPELL,'normal',())):
            with self.subTest(branch=branch):
                game=self.game(deck=(cid,),board=board,mode=mode);self.root(game,branch);saved=game.snapshot()
                with self.assertRaises(ResolutionError):self.pick_card(game,cid)
                self.assertEqual(game.snapshot(),saved);self.assertEqual(game.state.players[1].mana,2)

    def test_targetless_automatic_failure_still_consumes_original_spell_and_publishes_recipient(self):
        game=self.game(deck=(S+'target_spell',));selected=game.state.players[1].deck[0]
        self.root(game,SPELL);self.pick_card(game,S+'target_spell')
        cast=game.state.cast_history[-1];self.assertTrue(cast.completed);self.assertIsNotNone(cast.failure)
        self.assertEqual(game.state.entities[selected].zone,Zone.GRAVEYARD)
        self.assertEqual(original_recipient(game.state,next(e for e in game.events if e.kind=='card_discovered')).entity_id,selected)
        self.portable(game)

    def test_typed_offers_cannot_change_index_kind_or_old_schema_after_rehash(self):
        game=self.game(deck=(FILLER,FILLER));self.root(game,MINION);saved=game.snapshot()
        for field,value in (('index',99),('request',True)):
            changed=deepcopy(saved);count=0
            for wire in wires(changed['resolution_frame']):
                if wire.get('type','').endswith('.SelectDeckCardAction'):
                    wire['fields'][field]=value;count+=1
            self.assertGreater(count,0)
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(changed),fixture().registry)
        changed=deepcopy(saved);changed['schema_version']=589
        with self.assertRaises(SnapshotError):Game.from_snapshot(changed,fixture().registry)
        with self.assertRaises(ValueError):DiscoverDeckCardAction(1,CardType.WEAPON,True)

    def test_plain_original_deck_cast_recipe_rejects_other_destinations_and_explicit_policies(self):
        game=self.game(deck=(SAFE,));ref=CardReference.capture(game.state.entities[game.state.players[1].deck[0]])
        source=self.root(game,SPELL);self.pick_card(game,SAFE);result=game.state.card_discovery_history[-1].result
        request=CastStoredSpell(ref,1,source);validate_recipe(result,request)
        for changed in (replace(request,card=replace(ref,zone=Zone.HAND)),
                replace(request,card=replace(ref,player_id=2)),replace(request,choices='player')):
            with self.assertRaises(ValueError):validate_recipe(result,changed)

    def test_real_teacher_student_and_fandral_run_both_native_deck_branches_automatically(self):
        game=self.game(hand=('TIME_704',),deck=(FILLER,SAFE),board=(FANDRAL,))
        original=set(game.state.players[1].deck);self.play(game,'TIME_704');self.pick_card(game,ROOT)
        self.play(game,'TIME_704t');self.assertIsNone(game.state.pending_choice)
        native=next(c for c in game.state.cast_history if c.card_id==ROOT)
        self.assertEqual(native.branch_id,COMBINED)
        self.assertTrue(any(game.state.entities[i].card_id==FILLER for i in original.intersection(game.state.players[1].board)))
        cast=game.state.cast_history[-1];self.assertEqual(cast.card_id,SAFE);self.assertIn(cast.source_id,original)
        self.assertEqual(game.state.card_summon_history[-1].request.cause.cast_id,native.id)
        self.assertEqual(len(game.state.card_discovery_history),3);self.portable(game)


if __name__=='__main__':unittest.main()
