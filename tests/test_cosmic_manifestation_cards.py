"""One actual Outcast cast, two sequential semantic spell shuffles."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.cosmic_manifestation_cards import COSMIC, QUERY, POOL_ID, load_batch
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.effects import ChoiceOption, GrantKeyword, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CostSpec, LimitedTriggerSpec, Rarity, SpellSchool, SpellRepeatSpec, Zone
from hs_sim.engine.pools import GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery, resolve_candidates, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P='k128.test.'
SIGHT,STUDIES,RUNNER,YETI='CORE_BT_491','CORE_YOP_001','CORE_BT_480','CORE_CS2_182'
UNKNOWN,FOREIGN=P+'unknown',P+'foreign'
MEMBERS=(SIGHT,STUDIES,RUNNER,YETI,COSMIC)
CTX=GenerationContext('k128-complete-fixture','experimental')
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,
            CardMetadata(True,(CardClass.DEMON_HUNTER,),Rarity.COMMON,tribes=(),factions=(),subtypes=()),
            battlecry=False,deathrattle=False,choose_one=False))
    foreign=replace(r.card(STUDIES),id=FOREIGN,metadata=replace(r.card(STUDIES).metadata,classes=(CardClass.MAGE,),deck_identity=None))
    r.register_card(foreign);r.register_pool_card(PoolCard.from_definition(foreign))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID,'k128-complete-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid,3 if cid==SIGHT else 1)for cid in members),complete=True))
    def fail(c):raise ResolutionError('K128 deliberate shuffle continuation failure')
    scripts={'fail':fail,'counter':lambda c:(SetSecret(2,'EX1_287'),),
        'immune':lambda c:(GrantKeyword(c.state.players[2].hero_id,Keyword.IMMUNE,c.source_id),),
        'before':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('ok','Semantic spell shuffle',(GenerateFromPool(c.player_id,POOL_ID,QUERY,
                source_id=c.source_id,destination='deck',shuffle_actor_id=c.player_id),)),
            ChoiceOption('skip','Skip')),c.source_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,metadata=META,on_play=P+name))
    r.register_card(CardDefinition(P+'power','Spell Damage',CardType.MINION,health=8,spell_damage=1,metadata=META))
    r.register_card(CardDefinition(P+'repeat','Ordinary spell repeats',CardType.MINION,health=8,metadata=META,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==COSMIC
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        event='damage_dealt'if mode=='damage_wait'else'card_added_to_deck'
        r.register_card(CardDefinition(P+'watch','Original instruction observer',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class CosmicManifestationTests(unittest.TestCase):
    def game(self,hand=(COSMIC,),members=MEMBERS,mode=None,pool=True,context=CTX,board=(),enemy_board=(),hero='HERO_10'):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*4,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy_board,deck=(YETI,)*4)),seed=128,generation_context=context),registry(*self.config))

    def play(self,g,cid=COSMIC,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        if cid==COSMIC and target is None:target=g.state.players[2].hero_id
        g.apply(PlayCard(1,eid,target));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def made(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_added_to_deck'and e.source_id==source]

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry.__wrapped__(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(*self.config)).snapshot(),saved)
        for seat in (1,2):
            public=json.dumps(g.for_player(seat).observe())+json.dumps(g.for_player(seat).legal_actions())+json.dumps(g.player_events(seat))
            for field in ('deck_shuffle_history','deck_insertion','resolution_frame','rng_state','shuffle_actor_id'):
                self.assertNotIn('"'+field+'"',public)
        return other

    def nodes(self,value,suffix):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix):yield value['fields']
            for v in value.values():yield from self.nodes(v,suffix)
        elif isinstance(value,list):
            for v in value:yield from self.nodes(v,suffix)

    def test_complete_raw_two_faces_native_outcast_and_actual_spell_metadata(self):
        data=load_batch();row=data['cards'][0];raw=row['record'];card=registry().card(COSMIC)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(len(data['official_observations']['observations']),2)
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for ob in data['official_observations']['observations']:
            en=ob['locale']=='en_US';self.assertEqual(ob['face']['name'],raw['name_en'if en else'name']);self.assertEqual(norm(ob['face']['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual((card.cost,card.kind,card.metadata.classes,card.spell_school,card.keywords),
            (2,CardType.SPELL,(CardClass.DEMON_HUNTER,),SpellSchool.SHADOW,(Keyword.OUTCAST,)))
        self.assertFalse(data['cn_calibrated']);self.assertFalse(data['full_card_support'])

    def test_add_one_definition_preserves_full_existing_content_and_pool_rows(self):
        with patch('hs_sim.cards.cosmic_manifestation_cards.register_cosmic_manifestation_cards',lambda r:None):old=build_registry()
        new=build_registry();self.assertEqual(set(new.cards)-set(old.cards),{COSMIC})
        self.assertTrue(all(asdict(c)==asdict(new.card(cid))for cid,c in old.cards.items()))
        self.assertEqual(dict(old.pool_cards),dict(new.pool_cards));self.assertEqual(dict(old.pools),dict(new.pools))
        self.assertEqual(dict(old.generation_families),dict(new.generation_families))

    def test_plain_semantic_shuffle_is_finite_and_rejects_unreviewed_recipes(self):
        values=dict(player_id=1,pool_id=POOL_ID,query=QUERY,source_id=1,destination='deck',shuffle_actor_id=1)
        effect=GenerateFromPool(**values);self.assertIsNone(effect.minion_stats)
        for bad in ({'source_id':None},{'shuffle_actor_id':True},{'destination':'hand'},{'position':'top'},
                    {'query':PoolQuery(kinds=(CardType.MINION,),collectible=True)}, {'cost':CostSpec(delta=-1)},
                    {'replacement':False},{'temporary_until_turn':1},{'combined_shatter':True},
                    {'query':PoolQuery(kinds=(CardType.SPELL,))}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):GenerateFromPool(**(values|bad))

    def test_middle_position_deals_two_shuffles_one_and_pays_one_cast(self):
        g=self.game(hand=(YETI,COSMIC,YETI));source=self.play(g);s=g.state
        self.assertEqual(s.entities[s.players[2].hero_id].health,28);self.assertEqual(s.players[1].mana,38)
        self.assertEqual(len(s.cast_history),1);self.assertEqual(len(self.made(g,source)),1)
        row,=s.deck_shuffle_history;self.assertEqual((row.actor_id,row.player_id,row.declared_count,row.profile,row.source.entity_id),(1,1,1,'semantic',source))
        self.assertTrue(all(e.zone==Zone.DECK and not e.enchantments for e in self.made(g,source)))
        self.assertFalse(any(e.kind=='card_added_to_hand'and e.source_id==source for e in g.events))

    def test_both_original_hand_edges_repeat_two_pairs_with_independent_operations(self):
        for hand in ((COSMIC,YETI),(YETI,COSMIC)):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);source=self.play(g);s=g.state
                self.assertEqual(s.entities[s.players[2].hero_id].health,26);self.assertEqual(s.players[1].mana,38)
                self.assertEqual(len(s.cast_history),1);self.assertEqual(len(self.made(g,source)),2)
                self.assertEqual([r.id for r in s.deck_shuffle_history],[1,2]);self.assertEqual([r.declared_count for r in s.deck_shuffle_history],[1,1])
        self.portable(g)

    def test_sampling_and_random_insertions_follow_pair_order_and_complete_rng(self):
        g=self.game();rng=random.Random();rng.setstate(g._rng.getstate());deck=list(g.state.players[1].deck)
        candidates=resolve_candidates(g.registry,CTX,POOL_ID,QUERY,source_card_id=COSMIC,exclude_source_by_rule=True,player_id=1)
        expected=[];positions=[]
        for _ in range(2):
            expected.extend(sample_candidates(rng,candidates,1,replacement=True));positions.append(rng.randrange(len(deck)+len(positions)+1))
        source=self.play(g);made=self.made(g,source);self.assertEqual(tuple(e.card_id for e in made),tuple(expected))
        for e,pos in zip(made,positions):deck.insert(pos,e.id)
        self.assertEqual(g.state.players[1].deck,deck);self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(len({e.id for e in made}),2)

    def test_specified_demon_hunter_pool_ignores_current_hero_and_excludes_minions_foreign_source(self):
        g=self.game(hero='HERO_08',members=(*MEMBERS,FOREIGN));source=self.play(g)
        self.assertTrue(all(e.card_id in(SIGHT,STUDIES)for e in self.made(g,source)))
        ids={x.card_id for x in resolve_candidates(g.registry,CTX,POOL_ID,QUERY,source_card_id=COSMIC,exclude_source_by_rule=True,player_id=1)}
        self.assertEqual(ids,{SIGHT,STUDIES})

    def test_spell_power_scales_each_damage_without_extra_shuffle_or_cast(self):
        g=self.game(board=(P+'power',));source=self.play(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)
        self.assertEqual(len(self.made(g,source)),2);self.assertEqual(len(g.state.cast_history),1)

    def test_dead_original_target_does_not_retarget_or_cancel_later_shuffles(self):
        g=self.game(enemy_board=(RUNNER,YETI));target=g.state.players[2].board[0];other=g.state.players[2].board[1]
        source=self.play(g,target=target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[other].health,5)
        self.assertEqual(len(self.made(g,source)),2);self.assertEqual(len(g.state.deck_shuffle_history),2)

    def test_immune_enemy_target_is_illegal_and_counter_prevents_entire_body(self):
        from hs_sim.engine.errors import IllegalAction
        g=self.game(hand=(P+'immune',COSMIC));self.play(g,P+'immune');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before);self.assertFalse(g.state.deck_shuffle_history)
        h=self.game(hand=(P+'counter',COSMIC));self.play(h,P+'counter');source=self.play(h)
        self.assertEqual(h.state.entities[h.state.players[2].hero_id].health,30);self.assertFalse(self.made(h,source));self.assertFalse(h.state.deck_shuffle_history)

    def test_existing_spell_repeat_repeats_whole_body_without_extra_payment(self):
        g=self.game(board=(P+'repeat',));source=self.play(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22)
        self.assertEqual((len(self.made(g,source)),len(g.state.cast_history),g.state.players[1].mana),(4,2,38))

    def test_unknown_complete_pool_or_missing_context_rolls_back_damage_payment_rng(self):
        for kwargs in ({'members':(*MEMBERS,UNKNOWN)},{'pool':False},{'context':None}):
            with self.subTest(kwargs=kwargs):
                g=self.game(**kwargs);saved=g.snapshot();rng=g._rng.getstate()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),saved);self.assertEqual(g._rng.getstate(),rng)

    def test_empty_pool_keeps_both_damage_instructions_rng_neutral_and_no_shuffle_credit(self):
        g=self.game(members=(YETI,RUNNER,COSMIC));rng=g._rng.getstate();source=self.play(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.assertFalse(self.made(g,source))
        self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(g._rng.getstate(),rng)

    def test_first_damage_wait_restores_original_outcast_queue_and_rejects_bad_shuffle_fields(self):
        g=self.game(mode='damage_wait');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertFalse(g.state.deck_shuffle_history)
        other=self.portable(g)
        for key,value in (('shuffle_actor_id',True),('position','top'),('source_id',None)):
            saved=deepcopy(g.snapshot());next(self.nodes(saved['resolution_frame'],'GenerateFromPool'))[key]=value
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__(*self.config))
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.deck_shuffle_history),2)

    def test_first_shuffle_wait_keeps_committed_sample_and_failed_choice_boundary(self):
        g=self.game(mode='shuffle_wait');source=self.play(g);self.assertEqual(len(self.made(g,source)),1)
        other=self.portable(g);boundary=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),boundary)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.made(g,source)),2)
        self.portable(g)

    def test_real_insertion_reaction_failure_rolls_back_allocation_shuffle_rng_and_health(self):
        g=self.game(mode='fail');saved=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g._rng.getstate(),rng)

    def test_original_choice_branch_roundtrips_plain_spell_request_before_sampling(self):
        g=self.game(hand=(P+'before',));self.play(g,P+'before');self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(len(list(self.nodes(g.snapshot()['resolution_frame'],'GenerateFromPool'))),1)
        other=self.portable(g)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_old_schema_is_rejected_and_full_deck_contents_remain_private(self):
        g=self.game();source=self.play(g);saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__(*self.config))
        self.assertEqual(len(self.made(g,source)),2);self.portable(g)


if __name__=='__main__':unittest.main()
