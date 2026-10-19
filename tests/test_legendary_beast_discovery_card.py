"""Taka uses real selection, native memory and ordinary stats/deaths/summons."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.legendary_beast_discovery_card import CARD, load_batch, register_legendary_beast_discovery_card
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.discovery_memory import DeathrattleDiscoveryTarget, PROFILE, QUERY
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RandomDamage,
    RefreshMana, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import (DiscoverFromPool, GenerationContext, GenerateFromPool,
    PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CopyCard

P = 'taka.test.'
CTX = GenerationContext('taka-complete-experimental-domain', 'experimental')
POOL = 'constructed.cards'
GEN = tuple(P+'beast.'+str(i) for i in range(4))
FILL = 'CS2_182'
KILL, SILENCE, BOUNCE, COPY, BASE, TRIGGER, SUMMON, REFRESH, WATCH = (
    P+x for x in ('kill', 'silence', 'bounce', 'copy', 'base', 'trigger', 'summon', 'refresh', 'watch'))
UNKNOWN, COLOSSAL = P+'unknown', P+'colossal'
PLAIN = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
LEGEND = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.LEGENDARY, tribes=('beast',))


@lru_cache(maxsize=None)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_legendary_beast_discovery_card(r)
    for cid, attack, health, cls in zip(GEN, (4,8,0,2), (5,8,4,9),
            (CardClass.NEUTRAL, CardClass.HUNTER, CardClass.DRUID, CardClass.PRIEST)):
        card = CardDefinition(cid, cid, CardType.MINION, cost=4, attack=attack, health=health,
            metadata=replace(LEGEND, classes=(cls,)))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    bads = []
    for suffix, rarity, tribes, collectible in (('common',Rarity.COMMON,('beast',),True),
            ('dragon',Rarity.LEGENDARY,('dragon',),True),('token',Rarity.LEGENDARY,('beast',),False)):
        cid=P+suffix; card=CardDefinition(cid,cid,CardType.MINION,attack=9,health=9,
            metadata=CardMetadata(collectible,(CardClass.NEUTRAL,),rarity,tribes=tribes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card));bads.append(cid)
    # An unimplemented Colossal is excluded by Taka's explicit37.0 query rule,
    # not by absence of a behavior definition or a global generation ban.
    r.register_pool_card(PoolCard(COLOSSAL,CardType.MINION,10,LEGEND,
        keywords=(Keyword.COLOSSAL,),battlecry=False,deathrattle=False,choose_one=False,attack=10))
    members=GEN+tuple(bads)+(COLOSSAL,)
    if mode=='empty':members=tuple(bads)+(COLOSSAL,)
    if mode=='short':members=(GEN[0],*bads,COLOSSAL)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,4,LEGEND,
            battlecry=False,deathrattle=False,choose_one=False,attack=4));members+=UNKNOWN,
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL,P+'pool-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        COPY:lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id,mode='current',source_id=c.source_id),),
        BASE:lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base',source_id=c.source_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),),
        REFRESH:lambda c:(RefreshMana(c.player_id,10),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        extra={}if cid in (SUMMON,REFRESH)else {'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=PLAIN,**extra))
    def fail(c):raise ResolutionError('Taka deliberate rollback')
    r.register_behavior(P+'fail',fail)
    events={'stats-wait':'stats_changed','stats-kill':'stats_changed','stats-fail':'stats_changed',
        'early-kill':'battlecry_started','selection-kill':'choice_selected','summon-wait':'minion_summoned'}
    if mode in events:
        def watch(c):
            event=c.event;source=c.state.entities.get(event.source_id)
            if source is None:return ()
            if mode=='summon-wait':
                if source.card_id not in GEN:return ()
            elif source.card_id!=CARD:return ()
            if mode in ('stats-kill','early-kill','selection-kill'):return (Destroy(source.id,c.source_id),)
            bad=(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
            if mode=='stats-fail':return bad
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',bad)),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=PLAIN,
            triggers=(TriggerSpec(events[mode],WATCH),)))
    r.validate();r.freeze();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class LegendaryBeastTests(unittest.TestCase):
    def game(self,hand=(CARD,KILL),*,mode='normal',board=()):
        if mode in ('stats-wait','stats-kill','stats-fail','early-kill','selection-kill','summon-wait'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(FILL,)*12)),seed=249430,generation_context=CTX),registry('writer',mode))
    def play(self,g,cid=CARD,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def pick(self,g,option_id=None):
        q=g.state.pending_choice;o=next(o for o in q.options if o.id==option_id)if option_id else q.options[0]
        g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id
    def memory(self,g,eid):
        return next(a.deathrattle_memory for a in g.state.entities[eid].abilities if a.kind=='deathrattle'and a.deathrattle_memory is not None)
    def beasts(self,g):return [g.state.entities[i].card_id for i in g.state.players[1].board if g.state.entities[i].card_id in GEN]
    def portable(self,g,mode='normal'):
        r=registry('reader'if g.registry is registry('writer',mode)else 'writer',mode);saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved);return other

    def test_a00_complete_native_source_faces_and_full_assembly_match_minimal_host(self):
        from hs_sim.cards import build_registry as assembled
        from tools.card_batch import check_face
        data=load_batch();raw=data['cards'][0]['record']
        for x in data['official_observations']:check_face(raw,x['face'],x['locale'])
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(asdict(assembled().card(CARD)),asdict(registry('writer').card(CARD)))

    def test_a01_only_the_native_typed_memory_shape_is_accepted(self):
        from hs_sim.engine.pool_summons import query_from_dict
        self.assertEqual(query_from_dict(json.loads(json.dumps(asdict(QUERY)))),QUERY)
        for value in ([Keyword.COLOSSAL],('colossal',),(Keyword.COLOSSAL,Keyword.COLOSSAL)):
            with self.subTest(keywords_none=value),self.assertRaises(ValueError):PoolQuery(keywords_none=value)
        target=DeathrattleDiscoveryTarget(1,None,())
        spec=DiscoverFromPool(1,POOL,QUERY,source_id=1,destination='memory',memory_target=target)
        for change in ({'memory_target':True},{'destination':'hand'},{'count':2},{'discoveries':2},
                {'query':PoolQuery(kinds=(CardType.MINION,),collectible=True)}, {'cost':__import__('hs_sim.engine',fromlist=['CostSpec']).CostSpec(set_to=1)}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(spec,**change)
        with self.assertRaises(ValueError):GenerateFromPool(1,POOL,destination='memory')

    def test_b00_selection_gains_printed_stats_without_any_hand_copy_and_death_summons_it(self):
        g=self.game();source=self.play(g);before=len(g.state.entities);cid=self.pick(g);card=g.registry.card(cid)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(2+card.attack,2+card.health))
        self.assertEqual(len(g.state.entities),before);self.assertFalse(any(g.state.entities[i].card_id in GEN for i in g.state.players[1].hand))
        self.assertEqual(self.memory(g,source).discoveries[0].card_id,cid)
        self.assertEqual(len(g.state.card_discovery_history),1);self.assertEqual(g.state.players[1].mana,3)
        self.play(g,KILL,source);self.assertEqual(self.beasts(g),[cid]);self.portable(g)

    def test_b01_any_class_legendary_beasts_and_official_colossal_exclusion(self):
        g=self.game();self.play(g);offered={o.card_id for o in g.state.pending_choice.options}
        self.assertEqual(len(offered),3);self.assertTrue(offered<=set(GEN));self.assertNotIn(COLOSSAL,offered)
        self.assertTrue(any(g.registry.card(cid).metadata.classes!=(CardClass.NEUTRAL,)for cid in offered))

    def test_b02_original_discovery_wait_restores_then_selects_once(self):
        g=self.game();source=self.play(g);g=self.portable(g);self.pick(g)
        self.assertEqual(len(self.memory(g,source).discoveries),1)

    def test_b03_empty_short_and_unknown_domains_preserve_explicit_rules(self):
        g=self.game(mode='empty');rng=g.snapshot()['rng_state'];source=self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.memory(g,source).discoveries)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game(mode='short');self.play(g);self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),(GEN[0],));self.pick(g)
        for mode in ('unknown','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_c00_full_board_active_deathrattle_does_not_erase_later_natural_summon(self):
        g=self.game((CARD,TRIGGER,KILL),board=(FILL,)*6);source=self.play(g);cid=self.pick(g)
        self.play(g,TRIGGER,source);self.assertFalse(self.beasts(g));self.assertEqual(len(self.memory(g,source).discoveries),1)
        self.play(g,KILL,source);self.assertEqual(self.beasts(g),[cid])

    def test_c01_silence_removes_memory_and_plain_summon_has_no_fake_selection(self):
        g=self.game((CARD,SILENCE,KILL));source=self.play(g);self.pick(g);self.play(g,SILENCE,source);self.play(g,KILL,source)
        self.assertFalse(self.beasts(g))
        g=self.game((SUMMON,KILL));self.play(g,SUMMON);source=g.state.players[1].board[0]
        self.assertFalse(self.memory(g,source).discoveries);self.assertIsNone(g.state.pending_choice)
        self.play(g,KILL,source);self.assertFalse(self.beasts(g))

    def test_c02_current_copy_keeps_selected_memory_and_base_copy_and_bounce_reset_it(self):
        g=self.game((CARD,COPY,BASE,BOUNCE));source=self.play(g);self.pick(g);original=self.memory(g,source)
        self.play(g,COPY,source);self.play(g,BASE,source)
        copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD]
        self.assertEqual(self.memory(g,copies[0]),original);self.assertFalse(self.memory(g,copies[1]).discoveries)
        self.play(g,BOUNCE,source);self.assertFalse(self.memory(g,source).discoveries);self.portable(g)

    def test_c03_real_repeated_battlecry_keeps_two_original_selections_and_one_payment(self):
        g=self.game((CARD,KILL,KILL),board=('TIME_064',));source=self.play(g);first=self.pick(g)
        g=self.portable(g);second=self.pick(g);self.assertEqual(len(self.memory(g,source).discoveries),2)
        self.assertEqual(g.state.players[1].mana,3)
        provider=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='TIME_064')
        self.play(g,KILL,provider);self.play(g,KILL,source);self.assertEqual(self.beasts(g),[first,second])

    def test_c04_current_copy_new_battlecry_appends_to_its_own_inherited_originals(self):
        g=self.game((CARD,COPY,REFRESH,KILL));source=self.play(g);first=self.pick(g);self.play(g,COPY,source)
        self.play(g,REFRESH);copy=self.play(g);second=self.pick(g)
        self.assertEqual([x.card_id for x in self.memory(g,copy).discoveries],[first,second])
        self.assertEqual([x.card_id for x in self.memory(g,source).discoveries],[first])
        self.play(g,KILL,copy);self.assertEqual(self.beasts(g),[first,second])

    def test_d00_memory_precedes_stat_notification_that_kills_the_source(self):
        g=self.game(mode='stats-kill');source=self.play(g);cid=self.pick(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.beasts(g),[cid])

    def test_d01_source_dead_before_payload_or_selection_cannot_rewrite_accepted_death(self):
        for mode in ('early-kill','selection-kill'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g);self.pick(g)
                self.assertFalse(self.beasts(g));self.assertEqual(len(g.state.card_discovery_history),1)

    def test_e00_stat_wait_restores_committed_original_memory_and_late_failure_rolls_back(self):
        g=self.game(mode='stats-wait');source=self.play(g);self.pick(g)
        self.assertEqual(len(self.memory(g,source).discoveries),1);g=self.portable(g,'stats-wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,'fail')
        self.assertEqual(g.snapshot(),before);self.pick(g,'ok');self.assertIsNone(g.state.pending_choice)

    def test_e01_immediate_stat_failure_restores_original_offer_rng_memory_and_payment(self):
        g=self.game(mode='stats-fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,3)

    def test_e02_actual_deathrattle_summon_wait_restores_original_selected_face(self):
        g=self.game(mode='summon-wait');source=self.play(g);cid=self.pick(g);self.play(g,KILL,source)
        self.assertEqual(self.beasts(g),[cid]);g=self.portable(g,'summon-wait');self.pick(g,'ok')
        self.assertEqual(self.beasts(g),[cid])

    def test_f00_memory_fields_and_previous_schema_cannot_be_forged_on_restore(self):
        g=self.game();source=self.play(g);self.pick(g);saved=g.snapshot()
        def memory(s):return next(a['deathrattle_memory']for a in s['state']['entities'][str(source)]['abilities']if a['deathrattle_memory']is not None)
        for field,value in (('battlecry_id',100000),('discovery_id',100000),('card_id',FILL)):
            with self.subTest(field=field):
                bad=deepcopy(saved);memory(bad)['discoveries'][0][field]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry('reader'))
        bad=deepcopy(saved);del memory(bad)['discoveries']
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry('reader'))
        bad=deepcopy(saved);bad['schema_version']=425
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry('reader'))

    def test_f01_original_memory_and_choice_continuations_stay_private(self):
        g=self.game();self.play(g)
        for cid in GEN:self.assertNotIn(cid,json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))
        self.pick(g)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"deathrattle_memory"','"memory_target"','"original_offer"','"resolution_frame"','"rng_state"'):self.assertNotIn(key,wire)


if __name__=='__main__':unittest.main()
