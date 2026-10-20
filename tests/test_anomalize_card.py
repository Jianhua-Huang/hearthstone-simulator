"""Actual Anomalize cost bands, finite stat permutation and independent Fabled ban."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards.anomalize_card import CARD,load_batch,register_anomalize_card
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,
    PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import Buff,ChoiceOption,Damage,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AppendageSpec,SummonQuantitySpec
from hs_sim.engine.pools import (GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,
    resolve_candidates,sample_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.scrambled_summons import START,FINISH,ACCEPT
from hs_sim.engine.serialization import canonical_hash

P='anomalize.test.'
HERO,TEN,ONE,UNIT,WATCH,DOUBLE,LIMB,MISSING=(P+x for x in('hero','ten','one','unit','watch','double','limb','missing.fabled'))
CTX=GenerationContext('anomalize-native-fixture','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=14)
def registry(mode='plain',role='writer'):
    r=Registry('anomalize-native-v1');register_anomalize_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=200,
        metadata=replace(META,collectible=False,classes=(CardClass.MAGE,))))
    extra=dict(keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB),))if mode=='colossal'else{}
    for card in (CardDefinition(TEN,TEN,CardType.MINION,cost=10,attack=8,health=12,metadata=META,**extra),
        CardDefinition(ONE,ONE,CardType.MINION,cost=1,attack=0 if mode=='zero'else 3,health=4,
                       dormant_turns=2 if mode=='dormant'else 0,metadata=META),
        CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=3),
        CardDefinition(LIMB,LIMB,CardType.MINION,attack=6,health=6),
        CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=8,summon_quantities=(SummonQuantitySpec(),))):
        r.register_card(card)
    for cid in(TEN,ONE):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members=[TEN]if mode=='empty_one'else[TEN,ONE]
    if mode in('unknown','excluded'):
        r.register_pool_card(PoolCard(MISSING,CardType.MINION,10,replace(META,rarity=Rarity.LEGENDARY),attack=10))
        members.append(MISSING)
        if mode=='excluded':r.register_fabled_generation_exclusion(MISSING)
    r.register_pool(PoolDefinition('constructed.cards','v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('Anomalize fixture failure')))
    def watch(c):
        if c.event.kind=='minion_summoned':
            if c.state.entities[c.event.target_id].card_id!=TEN:return ()
            if mode=='grow':return (Buff(c.event.target_id,2,2,c.source_id),)
            if mode=='terminal':return (Damage(c.state.players[3-c.player_id].hero_id,999,c.source_id),)
            if mode=='wait':return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if c.event.kind=='stats_changed':
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='stat_wait':return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,triggers=tuple(
        TriggerSpec(kind,P+'watch')for kind in('minion_summoned','stats_changed'))))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class AnomalizeTests(unittest.TestCase):
    def game(self,mode='plain',board=(),player=1,seed=17):
        self.mode=mode
        setups=[PlayerSetup(HERO,hand=(CARD,),board=board,max_mana=10,mana=10),PlayerSetup(HERO)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=seed,generation_context=CTX),registry(mode))

    def play(self,g):
        pid=g.state.active_player;identity=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(pid,identity));return identity

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def event(self,g,kind=START):return next(e for e in g.events if e.kind==kind)

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=registry(self.mode,'reader')
        self.assertEqual(Game.from_snapshot(deepcopy(s),other).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),other).snapshot(),s)

    def test_a01_actual_seven_mana_arcane_spell_keeps_individual_four_values(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(data['evidence_only'][0]['record']['id'],CARD+'e')
        g=self.game();source=self.play(g);self.assertEqual(g.state.players[1].mana,3)
        self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[TEN,ONE])
        d=dict(self.event(g).data);self.assertEqual(d['values'],(8,12,3,4))
        self.assertEqual(sorted(d['indices']),[0,1,2,3])
        values=[value for i in g.state.players[1].board for value in(g.state.entities[i].attack,g.state.entities[i].health)]
        self.assertEqual(sorted(values),[3,4,8,12]);self.assertEqual(self.event(g).source_id,source)
        self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_a02_existing_board_minions_are_outside_original_group(self):
        g=self.game(board=(UNIT,));old=g.state.players[1].board[0];self.play(g)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(1,3))
        self.assertNotIn(old,[row[0]for row in dict(self.event(g).data)['targets']])

    def test_a03_current_summon_reaction_stats_are_frozen_before_permutation(self):
        g=self.game('grow',board=(WATCH,));self.play(g)
        self.assertEqual(dict(self.event(g).data)['values'],(10,14,3,4));self.portable(g)

    def test_b01_one_free_slot_scrambles_only_actual_ten_cost_delivery(self):
        g=self.game(board=(UNIT,)*6);self.play(g);d=dict(self.event(g).data)
        self.assertEqual(d['values'],(8,12));self.assertEqual(len(d['originals']),1)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(sum(e.kind=='summon_failed'for e in g.events),1);self.portable(g)

    def test_b02_full_board_has_empty_scramble_without_extra_randomness(self):
        g=self.game(board=(UNIT,)*7);self.play(g);d=dict(self.event(g).data)
        self.assertEqual(d['targets'],());self.assertEqual(d['rng_before'],d['rng_after'])
        self.assertEqual(sum(e.kind=='summon_failed'for e in g.events),2);self.portable(g)

    def test_b03_empty_one_cost_domain_does_not_create_a_fake_body(self):
        g=self.game('empty_one');self.play(g)
        self.assertEqual(len(dict(self.event(g).data)['originals']),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[TEN])

    def test_b04_unknown_eligible_member_fails_before_payment_or_partial_summon(self):
        g=self.game('unknown');before=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_b05_declared_fabled_exclusion_is_independent_of_executable_coverage(self):
        g=self.game('excluded');self.play(g)
        self.assertNotIn(MISSING,[g.state.entities[i].card_id for i in g.state.players[1].board])
        self.assertEqual(g.registry.fabled_generation_exclusions,frozenset((MISSING,)))

    def test_c01_dormant_contributes_operands_but_keeps_existing_stat_set_admission(self):
        g=self.game('dormant');self.play(g);d=dict(self.event(g).data)
        self.assertEqual(d['values'],(8,12,3,4));self.assertEqual([row[5]for row in d['targets']],[True,False])
        dormant=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==ONE)
        self.assertEqual((dormant.attack,dormant.health),(3,4));self.assertFalse(dormant.active);self.portable(g)

    def test_c02_zero_health_permutation_uses_normal_death_checkpoint(self):
        g=self.game('zero',seed=0);self.play(g);d=dict(self.event(g).data)
        self.assertEqual(sorted(d['values']),[0,4,8,12])
        assigned=[d['values'][i]for i in d['indices']]
        expected=sum(assigned[index]==0 for index in (1,3))
        self.assertEqual(expected,1)
        self.assertEqual(len(g.state.death_history),expected)
        self.portable(g)

    def test_c03_quantity_entries_keep_all_real_primary_deliveries(self):
        g=self.game(board=(DOUBLE,));self.play(g);d=dict(self.event(g).data)
        self.assertEqual(len(d['targets']),4);self.assertEqual(sorted(d['values']),[3,3,4,4,8,8,12,12])
        self.assertEqual(len(g.state.pool_summon_history),2);self.portable(g)

    def test_c04_colossal_appendage_is_not_an_extra_original_cost_band_body(self):
        g=self.game('colossal');self.play(g)
        self.assertEqual(len(dict(self.event(g).data)['targets']),2)
        limb=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==LIMB)
        self.assertEqual((limb.attack,limb.health),(6,6));self.portable(g)

    def test_d01_first_summon_wait_preserves_both_producers_and_original_scramble(self):
        g=self.game('wait',board=(WATCH,));self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.pool_summon_history),2);self.assertFalse(any(e.kind==START for e in g.events))
        self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(dict(self.event(g).data)['targets']),2)
        self.portable(g)

    def test_d02_stat_callbacks_wait_after_all_group_writes_and_restore(self):
        g=self.game('stat_wait',board=(WATCH,));self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(any(e.kind==FINISH for e in g.events))
        self.assertEqual(len(dict(self.event(g).data)['targets']),2);self.portable(g)
        while g.state.pending_choice is not None:self.choose(g)
        self.portable(g)

    def test_d03_late_stat_callback_failure_rolls_back_everything(self):
        g=self.game('fail',board=(WATCH,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_e01_second_player_has_its_own_attributed_original_group(self):
        g=self.game(player=2);self.play(g)
        self.assertEqual(self.event(g).player_id,2);self.assertEqual(len(g.state.players[2].board),2);self.portable(g)

    def test_e00_terminal_first_entry_preserves_interrupted_unclosed_group(self):
        g=self.game('terminal',board=(WATCH,));self.play(g)
        self.assertNotEqual(g.state.status,'playing')
        self.assertTrue(any(e.kind==ACCEPT for e in g.events))
        self.assertFalse(any(e.kind in(START,FINISH)for e in g.events))
        self.assertEqual(len(g.state.players[1].board),2);self.portable(g)

    def test_e02_rehashed_permutation_and_surviving_stat_layer_corruption_reject(self):
        g=self.game();self.play(g);s=g.snapshot()
        for change in('indices','originals','layer'):
            bad=deepcopy(s)
            if change=='layer':
                row=next(x for x in bad['state']['entities'].values()if x['card_id']==TEN)
                row['enchantments'][-1]['set_attack']=99
            else:
                event=next(e for e in bad['events']if e['kind']==START)
                if change=='indices':event['data']['indices']=list(reversed(event['data']['indices']))
                else:event['data']['originals']=event['data']['originals'][:-1]
            with self.subTest(change=change),self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(bad),registry())

    def test_e03_waiting_snapshot_cannot_drop_the_original_group_continuation(self):
        g=self.game('wait',board=(WATCH,));self.play(g);bad=deepcopy(g.snapshot());count=[0]
        def crop(value):
            if isinstance(value,list):
                for item in list(value):
                    if isinstance(item,dict)and item.get('type','').endswith('.ScramblePoolSummons'):
                        value.remove(item);count[0]+=1
                    else:crop(item)
            elif isinstance(value,dict):
                for item in value.values():crop(item)
        fields=bad['resolution_frame']['fields'];crop(fields['prefix']);crop(fields['continuation'])
        self.assertEqual(count[0],1)
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(bad),registry('wait'))

    def test_e04_player_events_do_not_expose_source_recipes_or_random_states(self):
        g=self.game();self.play(g);before=g.snapshot()
        for pid in(1,2):
            text=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            self.assertNotIn('rng_before',text);self.assertNotIn(START,text);self.assertNotIn(ACCEPT,text)
        self.assertEqual(g.snapshot(),before)

    def test_f01_real_fixed_candidate_pool_closes_informant_mage_discovery(self):
        from hs_sim.cards import build_registry
        from hs_sim.cards.candidate_generation_catalog import load_batch as candidates
        from hs_sim.cards.shadowed_informant_card import CARD as INFORMANT
        r=build_registry();ids=candidates()['candidate_root_ids'];context=GenerationContext('anomalize-real-candidates','experimental')
        r.register_pool(PoolDefinition('constructed.cards','all1188-v1',context.target_id,context.mode,
            tuple(PoolMember(cid)for cid in ids),complete=False))
        query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
        rows=resolve_candidates(r,context,'constructed.cards',query,source_card_id=INFORMANT)
        seed=next(n for n in range(1000)if CARD in sample_candidates(Random(n),rows,3,replacement=False))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(INFORMANT,),max_mana=10,mana=10,armor=200),
            PlayerSetup('HERO_08',armor=200)),seed=seed,generation_context=context),r)
        original=g.state.players[1].hand[0];g.apply(PlayCard(1,original));q=g.state.pending_choice
        option=next(o.id for o in q.options if o.card_id==CARD);g.apply(SelectChoice(1,q.id,(option,)))
        self.play(g);self.assertTrue(any(e.kind==FINISH for e in g.events))
        self.assertEqual(g.state.players[1].mana,1)
        self.assertNotIn('TIME_005',[m.card_id for row in g.state.pool_summon_history for m in row.spec.basis.candidates])
        self.assertNotIn('TIME_890',[m.card_id for row in g.state.pool_summon_history for m in row.spec.basis.candidates])
        saved=g.snapshot();self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)

    def test_g01_real_fabled_root_and_companions_are_excluded_but_remain_physical_cards(self):
        from hs_sim.cards import build_registry
        r=build_registry();spec=next(iter(r.fabled.values()));family=(spec.source_card_id,*spec.companion_card_ids)
        for cid in family:
            if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
        context=GenerationContext('real-fabled-exclusion','experimental')
        r.register_pool(PoolDefinition('fabled-proof','v1',context.target_id,context.mode,
            tuple(PoolMember(cid)for cid in(*family,'CATA_614')),complete=True))
        result=resolve_candidates(r,context,'fabled-proof',PoolQuery(),source_card_id=CARD)
        self.assertEqual([m.card_id for m in result],['CATA_614'])
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=family),PlayerSetup('HERO_08'))),r)
        self.assertEqual(tuple(g.state.entities[i].card_id for i in g.state.players[1].hand),family)


if __name__=='__main__':unittest.main()
