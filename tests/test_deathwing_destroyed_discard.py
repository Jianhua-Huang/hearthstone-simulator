"""Actual destruction occurrences, original payer and ordinary discard tails."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, FILLER
from hs_sim.cards.deathwing_destroyed_discard import CARD, ALIAS, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, Draw, InvokeBehavior, RequestChoice
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools import card_batch as batch

S='k560.'
WATCH,DRAWER,BROOD,KILLER,BOMB,IMMUNE,SHIELD=(S+x for x in ('watch','drawer','brood','killer','bomb','immune','shield'))
CTX=GenerationContext('k560-destroyed-count-discard-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','counted-deathwing-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def fail(c):raise ResolutionError('k560 deliberate continuation failure')
    def wait(c):return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
        ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
    def observe(c):
        if mode=='death_wait' and c.event.kind=='minion_died':
            did=dict(c.event.data).get('death_id');d=next((d for d in c.state.death_history if d.id==did),None)
            if d is not None and d.cause.source_card_id==CARD:return wait(c)
        if mode=='discard_wait' and c.event.kind=='card_discarded':
            source=c.state.entities.get(c.event.source_id)
            if source is not None and source.card_id==CARD:return wait(c)
        return ()
    def kill_source(c):
        source=next(i for p in c.state.players.values()for i in p.board if c.state.entities[i].card_id==CARD)
        return (Destroy(source,c.source_id),)
    scripts={'fail':fail,'draw':lambda c:(Draw(c.player_id,1,c.source_id),),
        'brood':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial('k545.unit',on_summon=S+'kill_child'),),SummonCause.capture(c)),),
        'kill_child':lambda c:(Destroy(original_named_reference(c).entity_id,c.source_id),),
        'kill_source':kill_source,'bomb':lambda c:(Damage(c.state.players[c.player_id].hero_id,30,c.source_id),)}
    for name,body in scripts.items():r.register_behavior(S+name,body)
    for cid,body,keywords in ((DRAWER,'draw',()),(BROOD,'brood',()),(KILLER,'kill_source',()),(BOMB,'bomb',()),
            (IMMUNE,None,(Keyword.IMMUNE,)),(SHIELD,None,(Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=2,
            deathrattle=S+body if body else None,keywords=keywords))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Diagnostic destruction/discard observer',CardType.WEAPON,durability=30,
        triggers=tuple(TriggerSpec(k,S+'observe')for k in ('minion_died','card_discarded'))))
    r.validate();return replace(fmt,context=CTX)


def wires(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):yield value
        for v in value.values():yield from wires(v,name)
    elif isinstance(value,list):
        for v in value:yield from wires(v,name)


def rehash(value):
    value['state_hash']=canonical_hash({k:v for k,v in value.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return value


class DeathwingDestroyedDiscardTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,board=(),enemy=(),deck=(FILLER,)*6,mode='normal'):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,max_mana=10,mana=10,
                weapon_card_id=WATCH if mode!='normal'else None),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*6)),seed=560,generation_context=CTX),fmt.registry)

    def test_full_original_and_alias_rows_explicit_primary_association_and_zero_match_gaps(self):
        data=load_batch();rows={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256']);raw=data['cards'][0]['record'];alias=data['evidence_only'][0]['record']
        self.assertEqual(raw,rows[CARD]);self.assertEqual(alias,rows[ALIAS])
        for face in data['official_faces']:
            batch.check_face(alias,face['face'],face['locale']);self.assertIn(raw['dbf_id'],face['face']['copyOfCardId'])
        for gap in data['missing_direct_primary_faces']:
            self.assertEqual(batch.sha(gap['response_file']),gap['response_sha256'])
            self.assertEqual(sum(f.get('id')==raw['dbf_id']for f in batch.read(gap['response_file'])['cards']),0)
        r=fixture().registry;self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(10,12,12))
        self.assertEqual(r.card(CARD).metadata.deck_identity,CARD);self.assertIsNotNone(r.card(CARD).battlecry)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_real_paid_batch_destroys_both_sides_through_shield_and_immunity_and_discards_exact_count(self):
        g=self.game((CARD,)+(FILLER,)*5,board=(IMMUNE,SHIELD),enemy=(FILLER,));source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].board,[source]);self.assertFalse(g.state.players[2].board)
        self.assertEqual((len(g.state.death_history),len(g.state.discard_history),len(g.state.players[1].hand)),(3,3,2))
        self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost),(0,10));self.assertFalse(g.state.draw_history)
        self.assertTrue(all(d.source_id==source for d in g.state.discard_history));self.portable(g)

    def test_no_other_minions_and_empty_hand_have_no_discard_or_rng(self):
        for hand,board in (((CARD,FILLER),()),((CARD,),(FILLER,))):
            with self.subTest(hand=hand):
                g=self.game(hand,board=board);rng=g.snapshot()['rng_state'];self.play(g,CARD)
                self.assertFalse(g.state.discard_history);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_dormant_and_location_are_not_original_destruction_victims(self):
        g=self.game((CARD,FILLER),board=('BT_004',),enemy=('CORE_REV_990',));self.play(g,CARD)
        self.assertFalse(g.state.death_history);self.assertFalse(g.state.discard_history)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,'BT_004')
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].card_id,'CORE_REV_990')

    def test_deathrattle_body_survives_and_does_not_increase_original_count(self):
        g=self.game((CARD,FILLER,FILLER),board=('BT_155',));self.play(g,CARD)
        self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['BT_155t',CARD])

    def test_reborn_body_is_new_and_is_not_destroyed_or_counted_twice(self):
        g=self.game((CARD,FILLER,FILLER),board=('ULD_275',));self.play(g,CARD)
        self.assertEqual(len(g.state.discard_history),1);body=self.entity(g,'ULD_275',zone='board')
        self.assertEqual(body.health,1);self.assertNotIn(Keyword.REBORN,body.keywords)

    def test_discard_uses_current_hand_after_the_original_deathrattle_draw(self):
        g=self.game((CARD,),board=(DRAWER,),deck=(FILLER,));original=g.state.players[1].deck[0];self.play(g,CARD)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual(g.state.discard_history[0].entity_id,original)

    def test_collateral_death_of_a_new_body_does_not_increase_the_count(self):
        g=self.game((CARD,FILLER,FILLER),board=(BROOD,));self.play(g,CARD)
        self.assertEqual(len(g.state.death_history),2);self.assertEqual(len(g.state.discard_history),1)

    def test_source_death_keeps_the_original_players_accepted_discard(self):
        g=self.game((CARD,FILLER,FILLER),board=(KILLER,));source=self.play(g,CARD)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discard_history),1);self.assertEqual(g.state.discard_history[0].source_id,source)

    def test_terminal_deathrattle_stops_the_remaining_discard(self):
        g=self.game((CARD,FILLER,FILLER),board=(BOMB,));self.play(g,CARD)
        self.assertEqual(g.state.winner,2);self.assertFalse(g.state.discard_history)

    def test_death_wait_restores_original_causes_and_bad_resume_is_atomic(self):
        g=self.game((CARD,)+(FILLER,)*4,board=(DRAWER,FILLER),mode='death_wait');self.play(g,CARD)
        self.assertFalse(g.state.discard_history);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.discard_history),2)

    def test_rehashed_original_player_cause_boundary_and_battlecry_cannot_be_rewritten(self):
        g=self.game((CARD,FILLER,FILLER),board=(FILLER,),mode='death_wait');self.play(g,CARD);saved=g.snapshot()
        for edit in ('player','cause','boundary','battlecry'):
            with self.subTest(edit=edit):
                value=deepcopy(saved);fields=next(wires(value['resolution_frame'],'CompleteDestroyedResources'))['fields']
                if edit=='player':fields['original']['fields']['player_id']=2
                if edit=='cause':fields['accepted']['tuple'].clear()
                if edit=='boundary':fields['first_death_id']+=1
                if edit=='battlecry':fields['original']['fields']['battlecry_id']+=99
                with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(value),fixture('death_wait').registry)
        saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('death_wait').registry)

    def test_discard_wait_keeps_the_accepted_count_and_resumes_each_success_once(self):
        g=self.game((CARD,)+(FILLER,)*5,board=(FILLER,),enemy=(FILLER,),mode='discard_wait');self.play(g,CARD)
        self.assertEqual(len(g.state.discard_history),1);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.discard_history),2)

    def test_real_frontier_discovery_and_one_mana_play_run_actual_counted_destruction(self):
        r=fixture().registry;rows=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([m.card_id for m in rows],[CARD]);g=self.game(('GDB_857',)+(FILLER,)*5,board=(FILLER,),enemy=(FILLER,))
        self.play(g,'GDB_857');self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==CARD));source=self.play(g,CARD)
        self.assertEqual(g.state.play_history[-1].cost,1);self.assertEqual(g.state.players[1].board,[source])
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.discard_history),2)


if __name__=='__main__':unittest.main()
