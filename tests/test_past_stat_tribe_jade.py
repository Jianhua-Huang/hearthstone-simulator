"""Five paid native roots, current physical tribes, and attributed Jade entry."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json, unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import build_registry, past_stat_tribe_jade as native
from hs_sim.engine import EndTurn, Game, PlayerSetup, ResolutionError, Scenario, SnapshotError
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    Draw, GainArmor, InvokeBehavior, RandomDamage, RequestChoice, Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem, jade_count
from hs_sim.engine.model import (BattlecryRepeatSpec, CardDefinition, CardType, CostSpec,
    Keyword, TargetSpec, TribeChangeSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.summon_quantities import validate_request
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format

VERANUS, FRIZZ, AYA, THERAZANE, EYSOR = native.ROOTS
P='k718.'
A,D,E,T,ALL,DORM,REPEAT = (P+x for x in ('plain','dragon','elemental','totem','all','dormant','repeat'))
KILL,HUSH,TAKE,INJURE,DRAW,BOOST,DRAGONS,ELEMENTALS,TOTEMS,LEGACY = (
    P+x for x in ('kill','hush','take','injure','draw','boost','dragons','elementals','totems','legacy'))
WAIT,FAIL=P+'wait',P+'fail'
CTX=GenerationContext(P+'explicit-physical-fixture','experimental')


@lru_cache(1)
def full():return build_registry()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format() if host else None
    r=h.registry if h else defaults()
    if not host:
        original=full()
        for cid in (*native.EXISTING,'DAL_575'):
            if cid not in r.cards:r.register_card(original.card(cid))
            if cid not in r.pool_cards:r.register_pool_card(original.pool_card(cid))
        if CLASSIC not in r.jade_families:r.register_jade_family(original.jade_families[CLASSIC])
        native.register_past_stat_tribe_jade(r)
    meta=metadata(collectible=False,tribes=())
    for cid,attack,health,cost,tribes in ((A,4,6,4,()),(D,5,7,3,('dragon',)),
            (E,3,5,4,('elemental',)),(T,2,4,2,('totem',)),(ALL,1,2,1,('all',)),
            (DORM,2,6,2,()),(REPEAT,1,12,2,())):
        extra={}
        if cid==DORM:extra['dormant_turns']=2
        if cid==REPEAT:extra['battlecry_repeats']=(BattlecryRepeatSpec(2),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,
            metadata=replace(meta,tribes=tribes),**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def boost(c):
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),2,3,c.source_id,cost=CostSpec(delta=-1))
            for z in ('hand','deck') for i in getattr(c.state.players[c.player_id],z)
            if c.state.entities[i].card_id==E)
    def tribes(c,tribe,printed):
        return tuple(ChangeMinionTribes(CardReference.capture(c.state.entities[i]),
            TribeChangeSpec('set',(tribe,) if c.state.entities[i].card_id==A else ()),c.source_id)
            for z in ('hand','deck') for i in getattr(c.state.players[c.player_id],z)
            if c.state.entities[i].card_id in (A,printed))
    helpers={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        INJURE:lambda c:(Buff(c.target_id,2,3,c.source_id),Damage(c.target_id,2,c.source_id)),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),BOOST:boost,
        DRAGONS:lambda c:tribes(c,'dragon',D),ELEMENTALS:lambda c:tribes(c,'elemental',E),
        TOTEMS:lambda c:tribes(c,'totem',T),LEGACY:lambda c:(SummonJadeGolem(c.player_id,c.source_id),)}
    for cid,body in helpers.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            **({'targeting':TargetSpec()} if cid in (KILL,HUSH,TAKE,INJURE) else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ValueError('K718 deliberate rollback')))
    def wait(c):
        target=c.state.entities.get(c.event.target_id)
        if target is None or target.jade_size is None:return ()
        row=next((x for x in c.state.jade_history if x.entity_id==target.id),None)
        if row is None:return ()
        options=[ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        source=c.state.entities.get(row.source_id)
        if source is not None and source.zone==Zone.BOARD:
            options.extend((ChoiceOption('kill_source','Kill original source',(Destroy(source.id,c.source_id),)),
                ChoiceOption('take_source','Take original source',(ChangeControl(source.id,3-source.controller),))))
        khadgar=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='DAL_575'),None)
        if khadgar is not None:options.append(ChoiceOption('kill_quantity','Kill quantity source',(Destroy(khadgar,c.source_id),)))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(WAIT,wait)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,metadata=meta,
        triggers=(TriggerSpec('minion_summoned',WAIT),)))
    r.validate();return r,h.context if h else CTX


class PastStatTribeJadeTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,deck=(),board=(),enemy=(),enemy_hand=(),enemy_deck=(A,)*8,host=False):
        self.mode='host' if host else 'small';r,context=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,
            mana=40,max_mana=40,mana_cap=40,armor=500),PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,
            board=enemy,mana=40,max_mana=40,mana_cap=40,armor=500)),seed=718,generation_context=context),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def golems(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].jade_size is not None]
    def costs(self,g,p=1,zone='deck'):return [g.state.entities[i].cost for i in getattr(g.state.players[p],zone)]
    def stats(self,g,p=1,zone='hand'):return [(g.state.entities[i].attack,g.state.entities[i].max_health) for i in getattr(g.state.players[p],zone)]
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,20);self.choose(g)
    def rejected(self,saved,change):
        s=deepcopy(saved);change(s)
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.registry_factory(self.mode,'independent-reader'))

    def test_full_five_rows_twelve_primary_faces_and_existing_four_templates(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),12)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_source_bound'])
        self.assertNotIn('MIS_701',full().cards)
        for cid in (*native.ROOTS,*native.EXISTING):
            self.assertEqual(fixture()[0].card(cid),full().card(cid))
        self.assertEqual(full().card(EYSOR).attack,0)
        self.assertIsNone(next(x['record']['attack'] for x in d['cards'] if x['record']['id']==EYSOR))

    def test_Veranus_sets_enemy_current_max_health_and_preserves_attack(self):
        g=self.game((INJURE,VERANUS),board=(A,),enemy=(A,D));enemy=self.unit(g,A,2).id
        self.play(g,INJURE,enemy);self.play(g,VERANUS)
        self.assertEqual((g.state.entities[enemy].attack,g.state.entities[enemy].health,g.state.entities[enemy].max_health),(6,1,1))
        self.assertEqual(self.unit(g,D,2).health,1);self.assertEqual(self.unit(g,A).health,6)
        self.assertEqual(g.state.players[1].mana,34);self.portable(g)

    def test_Veranus_excludes_dormant_and_non_board_cards(self):
        g=self.game((VERANUS,),enemy=(DORM,),enemy_hand=(D,),enemy_deck=(D,))
        self.play(g,VERANUS);self.assertEqual(self.unit(g,DORM,2).max_health,6)
        self.assertEqual(self.entity(g,D,2).max_health,7);self.assertEqual(self.costs(g,2),[3])

    def test_Veranus_empty_enemy_and_real_repeated_battlecry_pay_once(self):
        g=self.game((VERANUS,),board=(REPEAT,),enemy=(A,));self.play(g,VERANUS)
        self.assertEqual(self.unit(g,A,2).max_health,1);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(g.state.players[1].mana,34)

    def test_Frizz_reduces_every_physical_Dragon_in_own_deck(self):
        g=self.game((FRIZZ,D),deck=(D,D,ALL,A),enemy_deck=(D,))
        ids=tuple(g.state.players[1].deck);self.play(g,FRIZZ)
        self.assertEqual(tuple(g.state.players[1].deck),ids);self.assertEqual(self.costs(g),[1,1,0,4])
        self.assertEqual(self.entity(g,D).cost,3);self.assertEqual(self.costs(g,2),[3])

    def test_Frizz_uses_current_added_removed_and_All_tribes(self):
        g=self.game((DRAGONS,FRIZZ),deck=(A,D,ALL));self.play(g,DRAGONS);self.play(g,FRIZZ)
        self.assertEqual(self.costs(g),[2,3,0])

    def test_Frizz_repeat_stacks_to_zero_and_actual_draw_keeps_reduction(self):
        g=self.game((FRIZZ,DRAW),deck=(D,D),board=(REPEAT,));first=g.state.players[1].deck[0]
        self.play(g,FRIZZ);self.assertEqual(self.costs(g),[0,0]);self.play(g,DRAW)
        self.assertIn(first,g.state.players[1].hand);self.assertEqual(g.state.entities[first].cost,0)
        self.portable(g)

    def test_Aya_real_battlecry_and_natural_death_advance_growth_independently(self):
        g=self.game((AYA,KILL),board=(A,));source=self.play(g,AYA)
        self.assertEqual([x.jade_size for x in self.golems(g)],[1]);self.play(g,KILL,source)
        self.assertEqual([x.jade_size for x in self.golems(g)],[2,1]);self.assertEqual(jade_count(g.state,1),2)
        self.assertEqual(len(g.state.card_summon_history),2);self.assertEqual(g.state.players[1].mana,34)
        self.portable(g)

    def test_Aya_Khadgar_uses_same_size_for_extras_and_one_growth_per_root(self):
        g=self.game((AYA,KILL),board=('DAL_575',));source=self.play(g,AYA)
        self.assertEqual([x.jade_size for x in self.golems(g)],[1,1]);self.assertEqual(jade_count(g.state,1),1)
        self.play(g,KILL,source);self.assertEqual([x.jade_size for x in self.golems(g)],[2,2,1,1])
        self.assertEqual([x.size for x in g.state.jade_history],[1,2])
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,2]);self.portable(g)

    def test_Aya_repeated_battlecry_advances_two_logical_sizes_not_one(self):
        g=self.game((AYA,),board=(REPEAT,'DAL_575'));self.play(g,AYA)
        self.assertEqual(sorted(x.jade_size for x in self.golems(g)),[1,1,2,2])
        self.assertEqual(jade_count(g.state,1),2);self.assertEqual(g.state.players[1].mana,34)

    def test_Aya_last_board_slot_advances_growth_and_records_capacity(self):
        g=self.game((AYA,),board=(A,)*6);self.play(g,AYA)
        self.assertEqual(jade_count(g.state,1),1);self.assertEqual(self.golems(g),[])
        row=g.state.jade_history[0];root=g.state.card_summon_history[0]
        self.assertIsNone(row.entity_id);self.assertEqual(row.summon_root_id,root.id);self.portable(g)

    def test_Aya_silence_cancels_deathrattle_and_control_uses_new_players_growth(self):
        g=self.game((HUSH,KILL),board=(AYA,));source=self.unit(g,AYA).id
        self.play(g,HUSH,source);self.play(g,KILL,source);self.assertEqual(jade_count(g.state,1),0)
        g=self.game((TAKE,),board=(AYA,),enemy_hand=(KILL,));source=self.unit(g,AYA).id
        self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,KILL,source,player=2)
        self.assertEqual((jade_count(g.state,1),jade_count(g.state,2)),(0,1));self.assertEqual(self.golems(g,2)[0].jade_size,1)

    def test_Aya_waiting_entry_restores_and_invalid_choice_rolls_back_rng(self):
        g=self.game((AYA,),board=(WAIT,'DAL_575'));self.play(g,AYA)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g)
        self.assertEqual([x.jade_size for x in self.golems(g)],[1,1]);self.portable(g)

    def test_Aya_source_death_during_first_entry_keeps_outer_size_and_nested_growth(self):
        g=self.game((AYA,),board=(WAIT,'DAL_575'));source=self.play(g,AYA)
        self.choose(g,'kill_source');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        g=self.portable(g);self.finish(g)
        self.assertEqual(sorted(x.jade_size for x in self.golems(g)),[1,1,2,2])
        self.assertEqual([x.size for x in g.state.jade_history],[1,2]);self.portable(g)

    def test_Aya_quantity_source_dies_after_acceptance_but_extra_remains(self):
        g=self.game((AYA,KILL),board=(WAIT,'DAL_575'));source=self.play(g,AYA)
        self.choose(g,'kill_quantity');g=self.portable(g);self.finish(g)
        self.assertEqual([x.jade_size for x in self.golems(g)],[1,1])
        self.play(g,KILL,source);self.finish(g)
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,1])

    def test_Aya_control_during_entry_does_not_redirect_accepted_extra(self):
        g=self.game((AYA,),board=(WAIT,'DAL_575'));source=self.play(g,AYA)
        self.choose(g,'take_source');g=self.portable(g);self.finish(g)
        self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual([x.jade_size for x in self.golems(g)],[1,1]);self.assertEqual(self.golems(g,2),[])

    def test_Jade_material_rejects_nonplain_and_foreign_original_recipes(self):
        g=self.game((AYA,),board=(WAIT,));self.play(g,AYA);root=g.state.card_summon_history[0]
        for fields in ({'jade_id':0},{'jade_id':True},{'keywords':(Keyword.TAUNT,)},{'on_summon':FAIL}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(root.request.materials[0],**fields)
        for request in (replace(root.request,materials=(replace(root.request.materials[0],jade_id=99),)),
                replace(root.request,materials=(replace(root.request.materials[0],card_id=native.EXISTING[1]),))):
            with self.assertRaises(ValueError):validate_request(g.state,g.registry,request)
        with self.assertRaises(ValueError):replace(root.request,player_id=2)

    def test_Jade_snapshot_cannot_rebind_original_root_or_first_delivery(self):
        g=self.game((AYA,),board=('DAL_575',));self.play(g,AYA);saved=g.snapshot()
        for key,value in (('summon_root_id',99),('summon_root_id',None),('entity_id',g.state.players[1].hero_id)):
            self.rejected(saved,lambda s,key=key,value=value:s['state']['jade_history'][0].update(**{key:value}))

    def test_legacy_unattributed_Jade_refuses_quantity_without_silent_under_summon(self):
        g=self.game((LEGACY,),board=('DAL_575',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,LEGACY)
        self.assertEqual(g.snapshot(),before)

    def test_Therazane_doubles_current_hand_and_deck_Elementals_only(self):
        g=self.game((BOOST,KILL,E,ALL,A),deck=(E,A),board=(THERAZANE,E),enemy_hand=(E,))
        self.play(g,BOOST);source=self.unit(g,THERAZANE).id;self.play(g,KILL,source)
        self.assertEqual((self.entity(g,E).attack,self.entity(g,E).max_health,self.entity(g,E).cost),(10,16,3))
        self.assertEqual((self.entity(g,ALL).attack,self.entity(g,ALL).max_health),(2,4))
        self.assertEqual(self.stats(g,zone='deck'),[(10,16),(4,6)])
        self.assertEqual((self.unit(g,E).attack,self.unit(g,E).max_health),(3,5))
        self.assertEqual((self.entity(g,E,2).attack,self.entity(g,E,2).max_health),(3,5));self.portable(g)

    def test_Therazane_uses_current_added_and_removed_tribes(self):
        g=self.game((ELEMENTALS,KILL,A,E),deck=(A,E),board=(THERAZANE,))
        self.play(g,ELEMENTALS);self.play(g,KILL,self.unit(g,THERAZANE).id)
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).max_health),(8,12))
        self.assertEqual((self.entity(g,E).attack,self.entity(g,E).max_health),(3,5))
        self.assertEqual(self.stats(g,zone='deck'),[(8,12),(3,5)])

    def test_Therazane_two_actual_deaths_double_updated_values_again(self):
        g=self.game((KILL,KILL,E),board=(THERAZANE,THERAZANE));self.play(g,KILL,self.unit(g,THERAZANE).id)
        self.play(g,KILL,self.unit(g,THERAZANE).id)
        self.assertEqual((self.entity(g,E).attack,self.entity(g,E).max_health),(12,20))

    def test_Therazane_silence_suppresses_and_Taunt_is_real(self):
        g=self.game((HUSH,KILL,E),board=(THERAZANE,));source=self.unit(g,THERAZANE).id
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)
        self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertEqual((self.entity(g,E).attack,self.entity(g,E).max_health),(3,5))

    def test_Eysor_own_end_turn_buffs_other_current_Totems_in_all_three_zones(self):
        g=self.game((EYSOR,T,ALL,A),deck=(T,A),board=(T,),enemy=(T,),enemy_hand=(T,))
        source=self.play(g,EYSOR);g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(0,4))
        self.assertEqual((self.unit(g,T).attack,self.unit(g,T).max_health),(3,5))
        self.assertEqual((self.entity(g,T).attack,self.entity(g,T).max_health),(3,5))
        self.assertEqual((self.entity(g,ALL).attack,self.entity(g,ALL).max_health),(2,3))
        self.assertEqual(self.stats(g,zone='deck'),[(3,5),(4,6)])
        self.assertEqual((self.unit(g,T,2).attack,self.unit(g,T,2).max_health),(2,4))
        g.apply(EndTurn(2));self.assertEqual(self.unit(g,T).attack,3);self.portable(g)

    def test_Eysor_excludes_physical_source_but_other_same_face_is_buffed(self):
        g=self.game((EYSOR,),board=(EYSOR,));self.play(g,EYSOR);g.apply(EndTurn(1))
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health) for i in g.state.players[1].board],[(1,5),(1,5)])

    def test_Eysor_current_added_removed_and_All_tribes_keep_cost(self):
        g=self.game((TOTEMS,A,T,ALL),deck=(A,T,ALL),board=(EYSOR,))
        self.play(g,TOTEMS);g.apply(EndTurn(1))
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).max_health,self.entity(g,A).cost),(5,7,4))
        self.assertEqual((self.entity(g,T).attack,self.entity(g,T).max_health),(2,4))
        self.assertEqual(self.stats(g,zone='deck'),[(5,7),(2,4),(2,3)])

    def test_Eysor_silence_stops_real_end_turn_trigger(self):
        g=self.game((HUSH,T),board=(EYSOR,));self.play(g,HUSH,self.unit(g,EYSOR).id);g.apply(EndTurn(1))
        self.assertEqual((self.entity(g,T).attack,self.entity(g,T).max_health),(2,4))

    def test_all_five_actual_host_entries_execute_without_reduced_pools(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,KILL,E),deck=(D,E,T),enemy=(A,),host=True)
                source=self.play(g,cid);self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)
                if cid==VERANUS:self.assertEqual(self.unit(g,A,2).health,1)
                elif cid==FRIZZ:self.assertEqual(self.costs(g)[0],1)
                elif cid==AYA:self.assertEqual([e.jade_size for e in self.golems(g)],[1])
                elif cid==THERAZANE:
                    self.play(g,KILL,source);self.assertEqual(self.entity(g,E).attack,6)
                else:
                    g.apply(EndTurn(1));self.assertEqual(self.stats(g,zone='deck')[-1],(3,5))
                original=fixture('independent-host-pool-reader',True)[0]
                self.assertEqual(dict(g.registry.pools),dict(original.pools))

    def test_schema_and_both_player_views_preserve_private_Jade_recipe(self):
        g=self.game((AYA,),board=(WAIT,));self.play(g,AYA);saved=g.snapshot()
        for version in (SNAPSHOT_SCHEMA_VERSION-1,SNAPSHOT_SCHEMA_VERSION+1,True):
            self.rejected(saved,lambda s,version=version:s.update(schema_version=version))
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe())
            for word in ('jade_history','summon_root_id','JadeEntryMaterial','card_summon_history'):
                self.assertNotIn('"'+word+'"',view)

