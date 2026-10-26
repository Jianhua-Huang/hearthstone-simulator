"""Native endless Infuse: physical numbers, actual deaths and frozen payloads."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, FILLER
from hs_sim.cards.endless_infuse_card import CARD, INFUSED, ORIGINAL, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, Keyword, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, DamageBatch, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.infused_battlecries import LABEL, value
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard
from tools import card_batch as batch

S='k561.'
UNIT, WATCH=S+'unit',S+'watch'
CTX=GenerationContext('k561-endless-infuse-native-test','experimental')


def native(c, zone=Zone.HAND):
    return next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone.value)
        if c.state.entities[i].card_id in (CARD,INFUSED))


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','native-endless-infuse-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    def copy(c, mode):
        return (CopyCard(CardReference.capture(native(c)),c.player_id,mode=mode,source_id=c.source_id),)
    def fail(c):raise ResolutionError('k561 deliberate resume failure')
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id),)
    def observer(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if mode=='progress_wait' and e.kind=='hand_progressed' and e.amount==0 and c.state.entities[e.target_id].card_id==INFUSED:
            return wait(c)
        if mode=='damage_wait' and e.kind=='damage_dealt' and source is not None and source.card_id in (CARD,INFUSED):
            return wait(c)
        return ()
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'sweep':lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id)for i in c.state.players[c.player_id].board)),),
        'copy_current':lambda c:copy(c,'current'),
        'copy_base':lambda c:copy(c,'base'),
        'bounce':lambda c:(ReturnToHand(c.target_id,cost=CostSpec(set_to=1)),),
        'silence':lambda c:(Silence(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,UNIT),),
        'discard':lambda c:(DiscardCard(CardReference.capture(native(c)),c.source_id),),
        'copy_discard':lambda c:(CopyCard(c.state.discard_history[-1],c.player_id,mode='base',source_id=c.source_id),),
        'copy_played':lambda c:(CopyCard(next(p.minion_copy_material for p in reversed(c.state.play_history)
            if p.card_id in (CARD,INFUSED)),c.player_id,mode='base',source_id=c.source_id),),
        'copy_death':lambda c:(CopyCard(next(d for d in reversed(c.state.death_history)if d.card_id in (CARD,INFUSED)),
            c.player_id,mode='base',source_id=c.source_id),),
        'copy_board':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base',cause=SummonCause.capture(c)),),
        'fail':fail,
        'observe':observer,
    }
    for name,body in scripts.items():
        r.register_behavior(S+name,body)
        if name not in ('fail','observe'):
            r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name,
                requires_target=name in ('kill','bounce','silence','transform','copy_board')))
    r.register_card(CardDefinition(UNIT,'Infuse witness',CardType.MINION,attack=1,health=1))
    r.register_card(CardDefinition(WATCH,'Infuse boundary observer',CardType.WEAPON,durability=20,
        triggers=tuple(TriggerSpec(e,S+'observe')for e in ('hand_progressed','damage_dealt'))))
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


class EndlessInfuseCardTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,board=(),enemy=(),deck=(FILLER,)*4,mode='normal',mana=60):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,mana=mana,max_mana=mana,mana_cap=max(10,mana),
                weapon_card_id=WATCH if mode!='normal'else None),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*4)),seed=561,generation_context=CTX),fixture(mode).registry)

    def prepared(self,extra=(),deaths=3,mode='normal'):
        g=self.game((CARD,S+'sweep')+extra,board=(UNIT,)*deaths,mode=mode)
        original=self.entity(g,CARD).id;self.play(g,S+'sweep')
        return g,original

    def test_full_rows_four_primary_faces_and_explicit_core_child_association(self):
        d=load_batch();rows={r['id']:r for r in batch.read(d['source'])}
        self.assertEqual(batch.sha(d['source']),d['source_sha256'])
        for item in d['cards']+d['dependencies']+d['evidence_only']:
            self.assertEqual(item['record'],rows[item['record']['id']])
        for face in d['official_faces']:
            batch.check_face(rows[face['card_id']],face['face'],face['locale'],d['display_normalizations'][face['card_id']])
        r=fixture().registry
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(10,10,10))
        self.assertEqual((r.infused_battlecry_profiles[CARD].initial_damage,r.infused_battlecry_profiles[INFUSED].initial_damage),(5,6))
        self.assertNotIn(ORIGINAL,r.cards);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        face=next(f for f in d['official_faces']if f['card_id']==INFUSED)
        with self.assertRaises(ValueError):batch.check_face(rows[INFUSED],face['face'],face['locale'],{'{0}':'','{1}':'99'})

    def test_real_payment_five_unit_packets_and_actual_lifesteal(self):
        g=self.game((CARD,'k545.hurt_hero'),mana=10);self.play(g,'k545.hurt_hero');source=self.play(g,CARD)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(10,0))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(g.state.battlecry_history[-1].payload.infused_damage,5)
        self.assertEqual(value(g.state.entities[source]),5);self.portable(g)

    def test_first_and_repeating_stages_consume_actual_friendly_deaths_once(self):
        g=self.game((CARD,)+(S+'kill',)*4,board=(UNIT,)*4);source=self.entity(g,CARD).id
        for deaths in range(1,5):
            self.play(g,S+'kill',self.entity(g,UNIT,zone='board').id);e=g.state.entities[source];a=progress_ability(e)
            self.assertEqual((e.card_id,value(e),a.progress_value,a.progress_completions),
                (CARD if deaths<2 else INFUSED,5+deaths//2,deaths%2,deaths//2))
            self.assertEqual(len(a.progress_keys),deaths)
        self.assertEqual(value(g.state.entities[source]),7)

    def test_fresh_infused_face_starts_at_six_without_first_stage_off_by_one(self):
        g=self.game((INFUSED,S+'sweep'),board=(UNIT,UNIT));source=self.entity(g,INFUSED).id
        self.assertEqual(value(g.state.entities[source]),6);self.play(g,S+'sweep')
        self.assertEqual((value(g.state.entities[source]),progress_ability(g.state.entities[source]).progress_completions),(7,1))

    def test_enemy_deaths_and_native_cards_outside_hand_do_not_infuse(self):
        g=self.game((CARD,S+'kill',S+'sweep'),board=(UNIT,),enemy=(UNIT,),deck=(CARD,))
        held=self.entity(g,CARD).id;stored=g.state.players[1].deck[0]
        self.play(g,S+'kill',self.entity(g,UNIT,player=2,zone='board').id)
        self.assertEqual((value(g.state.entities[held]),progress_ability(g.state.entities[held]).progress_value),(5,0))
        self.play(g,S+'sweep');self.assertEqual(progress_ability(g.state.entities[held]).progress_value,1)
        self.assertEqual((value(g.state.entities[stored]),progress_ability(g.state.entities[stored]).progress_value),(5,0))

    def test_two_physical_hand_cards_have_independent_parameters_and_witnesses(self):
        g=self.game((CARD,CARD,S+'sweep'),board=(UNIT,)*4);ids=g.state.players[1].hand[:2];self.play(g,S+'sweep')
        self.assertEqual([value(g.state.entities[i])for i in ids],[7,7])
        self.assertNotEqual(g.state.entities[ids[0]].enchantments[0].id,g.state.entities[ids[1]].enchantments[0].id)
        self.play(g,INFUSED);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(value(g.state.entities[ids[1]]),7)

    def test_current_copy_inherits_damage_and_partial_progress_then_advances_independently(self):
        g,source=self.prepared((S+'copy_current',S+'kill',UNIT));self.play(g,S+'copy_current')
        copied=next(i for i in g.state.players[1].hand if i!=source and g.state.entities[i].card_id==INFUSED)
        self.assertEqual([progress_ability(g.state.entities[i]).progress_value for i in (source,copied)],[1,1])
        target=self.play(g,UNIT);self.play(g,S+'kill',target)
        self.assertEqual([value(g.state.entities[i])for i in (source,copied)],[7,7]);self.portable(g)

    def test_base_copy_keeps_earned_number_and_resets_unfinished_progress(self):
        g,source=self.prepared((S+'copy_base',S+'kill',UNIT));self.play(g,S+'copy_base')
        copied=next(i for i in g.state.players[1].hand if i!=source and g.state.entities[i].card_id==INFUSED)
        self.assertEqual((value(g.state.entities[copied]),progress_ability(g.state.entities[copied]).progress_value),(6,0))
        target=self.play(g,UNIT);self.play(g,S+'kill',target)
        self.assertEqual([value(g.state.entities[i])for i in (source,copied)],[7,6])

    def test_bounce_keeps_damage_and_restarts_partial_progress_on_same_physical_card(self):
        g,source=self.prepared((S+'bounce',));self.play(g,INFUSED);self.play(g,S+'bounce',source)
        e=g.state.entities[source];self.assertEqual((e.zone,e.card_id,value(e),progress_ability(e).progress_value),(Zone.HAND,INFUSED,6,0))
        self.play(g,INFUSED);self.assertEqual(g.state.battlecry_history[-1].payload.infused_damage,6);self.portable(g)

    def test_silence_keeps_intrinsic_number_and_bounce_restores_printed_battlecry(self):
        g,source=self.prepared((S+'silence',S+'bounce'));self.play(g,INFUSED);self.play(g,S+'silence',source)
        self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[source].keywords);self.assertEqual(value(g.state.entities[source]),6)
        self.play(g,S+'bounce',source);self.assertIn(Keyword.LIFESTEAL,g.state.entities[source].keywords)
        self.play(g,INFUSED);self.assertEqual(g.state.battlecry_history[-1].payload.infused_damage,6)

    def test_transform_clears_the_native_parameter_without_altering_accepted_history(self):
        g,source=self.prepared((S+'transform',));self.play(g,INFUSED);self.play(g,S+'transform',source)
        self.assertEqual(g.state.entities[source].card_id,UNIT);self.assertIsNone(value(g.state.entities[source]))
        self.assertEqual(g.state.battlecry_history[-1].payload.infused_damage,6);self.portable(g)

    def test_played_base_copy_uses_original_submitted_damage_after_source_transform(self):
        g,source=self.prepared((S+'transform',S+'copy_played'));self.play(g,INFUSED);self.play(g,S+'transform',source)
        self.play(g,S+'copy_played');e=self.entity(g,INFUSED)
        self.assertEqual((value(e),progress_ability(e).progress_value),(6,0));self.portable(g)

    def test_discard_base_copy_retains_original_earned_damage(self):
        g,source=self.prepared((S+'discard',S+'copy_discard'));self.play(g,S+'discard')
        self.assertEqual(g.state.discard_history[-1].infused_damage,6);self.play(g,S+'copy_discard')
        e=self.entity(g,INFUSED);self.assertNotEqual(e.id,source);self.assertEqual(value(e),6);self.portable(g)

    def test_death_base_copy_retains_intrinsic_number_and_does_not_cast_battlecry(self):
        g,source=self.prepared((S+'kill',S+'copy_death'));self.play(g,INFUSED);self.play(g,S+'kill',source)
        self.play(g,S+'copy_death');self.assertEqual(value(self.entity(g,INFUSED)),6)
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_attributed_board_base_copy_freezes_the_native_parameter(self):
        g,source=self.prepared((S+'copy_board',));self.play(g,INFUSED);self.play(g,S+'copy_board',source)
        copies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==INFUSED]
        self.assertEqual([value(e)for e in copies],[6,6]);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_completed_progress_wait_restores_once_and_failed_choice_is_atomic(self):
        g,source=self.prepared(mode='progress_wait');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(value(g.state.entities[source]),6);saved=g.snapshot();other=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((value(g.state.entities[source]),progress_ability(g.state.entities[source]).progress_value),(6,1))

    def test_split_packet_wait_restores_budget_rng_payment_and_damage(self):
        g,source=self.prepared(mode='damage_wait');self.play(g,INFUSED);saved=g.snapshot();other=self.portable(g)
        self.assertEqual(g.state.battlecry_history[-1].payload.infused_damage,6)
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):
            while game.state.pending_choice is not None:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)

    def test_rehashed_bad_native_parameter_payload_and_old_schema_are_rejected(self):
        g,source=self.prepared();self.play(g,INFUSED);saved=g.snapshot()
        mutations=('bool','mixed','minimum','payload','submission','missing','foreign')
        for kind in mutations:
            with self.subTest(kind=kind):
                bad=deepcopy(saved);rows=list(walk(bad));e=next(x for x in rows if x.get('id')==source and x.get('card_id')==INFUSED and 'enchantments'in x and 'zone'in x)
                enchant=next(x for x in e['enchantments']if x['label']==LABEL)
                if kind=='bool':enchant['infused_damage']=True
                elif kind=='mixed':enchant['attack']=1
                elif kind=='minimum':enchant['infused_damage']=5
                elif kind=='missing':e['enchantments'].remove(enchant)
                elif kind=='foreign':e['card_id']=UNIT
                elif kind=='payload':
                    for x in rows:
                        if 'ability_id'in x and 'infused_damage'in x and x['infused_damage']is not None:x['infused_damage']+=1
                else:
                    for x in rows:
                        if 'play_id'in x and 'permanent_stats'in x and x.get('infused_damage')is not None:x['infused_damage']+=1
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader').registry)
        bad=deepcopy(saved);bad['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture().registry)

    def test_real_frontier_discovery_keeps_set_one_price_through_native_upgrade(self):
        r=fixture().registry;members=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([(m.card_id,m.weight)for m in members],[(CARD,1)])
        g=self.game(('GDB_857',S+'sweep'),board=(UNIT,UNIT));self.play(g,'GDB_857')
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==CARD));self.play(g,S+'sweep')
        source=self.play(g,INFUSED);self.assertEqual(g.state.play_history[-1].cost,1)
        self.assertEqual((g.state.entities[source].card_id,g.state.battlecry_history[-1].payload.infused_damage),(INFUSED,6));self.portable(g)


if __name__=='__main__':unittest.main()
