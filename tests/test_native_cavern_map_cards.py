"""Actual Frost Rune discovery retains the original physical Map offer."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_cavern_map_cards import CARD, BODY, POOL, load_batch, register_native_cavern_map_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice, SnapshotError, SpellSchool)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Runes
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION

PREFIX='k168.'
HERO,F0,F1,F2,SCHOOL,BLOOD,NONE,MISSING,UNKNOWN=(PREFIX+x for x in
    ('hero','frost-minion','frost-shadow','frost-fire','school-only','blood','none','missing','unknown'))
CONTEXT=GenerationContext('k168-explicit-fixture','experimental')
META=CardMetadata(True,(CardClass.DEATH_KNIGHT,),Rarity.COMMON,runes=Runes(),tribes=())


@lru_cache(maxsize=None)
def registry(pool='all',role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent immutable fixture role required')
    r=Registry('cavern-map-'+pool);register_native_cavern_map_cards(r)
    r.register_behavior(PREFIX+'noop',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=replace(META,collectible=False,classes=(CardClass.MAGE,))))
    specs=((F0,CardType.MINION,Runes(frost=1),None),
           (F1,CardType.SPELL,Runes(frost=1),SpellSchool.SHADOW),
           (F2,CardType.SPELL,Runes(blood=1,frost=1),SpellSchool.FIRE),
           (SCHOOL,CardType.SPELL,Runes(),SpellSchool.FROST),
           (BLOOD,CardType.MINION,Runes(blood=1),None),
           (NONE,CardType.MINION,Runes(),None))
    for cid,kind,runes,school in specs:
        card=CardDefinition(cid,cid,kind,cost=1,attack=1 if kind==CardType.MINION else 0,
            health=3 if kind==CardType.MINION else 0,on_play=PREFIX+'noop'if kind==CardType.SPELL else None,
            spell_school=school,metadata=replace(META,runes=runes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(F0,F1,F2,SCHOOL,BLOOD,NONE,CARD) if pool not in ('empty','single') else (
        (SCHOOL,BLOOD,NONE) if pool=='empty' else (F0,))
    if pool in ('unadapted','unknown'):
        cid=MISSING if pool=='unadapted'else UNKNOWN
        r.register_pool_card(PoolCard(cid,CardType.MINION,1,
            replace(META,runes=Runes(frost=1)if pool=='unadapted'else None)))
        members+=(cid,)
    r.register_pool(PoolDefinition(POOL,'v1',CONTEXT.target_id,CONTEXT.mode,
                                  tuple(PoolMember(i)for i in members),complete=True))
    r.validate();r.freeze();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
                                       if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class CavernMapTests(unittest.TestCase):
    def game(self,*,pool='all',pid=1,hand=None):
        self.pool=pool;self.pid=pid
        hand=(CARD,)if hand is None else hand
        players=tuple(PlayerSetup(HERO,hand=hand if p==pid else (),deck=(NONE,)*8,
                                  mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,seed=168,active_player=pid,generation_context=CONTEXT),registry(pool))
    def play(self,g,cid,entity=None):
        e=g.state.entities[entity]if entity is not None else next(g.state.entities[i]
            for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None))
        return e.id
    def select(self,g,cid=None):
        q=g.state.pending_choice;o=next(o for o in q.options if cid is None or o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id
    def root(self,g):return g.state.hand_choice_followups[-1]
    def portable(self,g):
        reader=registry(self.pool,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_complete_source_retains_frost_rune_cost_and_no_spell_school(self):
        from tools.card_batch import check_face
        d=load_batch();raw=d['cards'][0]['record'];card=registry().card(CARD)
        self.assertEqual((card.cost,card.on_play,card.metadata.runes,card.spell_school),
                         (1,BODY,Runes(frost=2),None))
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        self.assertEqual(len(d['official_observations']),2)

    def test_paid_map_matches_printed_frost_runes_across_card_kinds_and_schools(self):
        g=self.game();self.play(g,CARD);root=self.root(g)
        self.assertEqual(root.request.query.runes_any,('frost',))
        self.assertEqual({x.card_id for x in root.available_pool},{F0,F1,F2})
        self.assertEqual(g.state.players[1].mana,19)
        self.assertEqual(g.registry.card(HERO).metadata.classes,(CardClass.MAGE,))
        self.portable(g)

    def test_original_selected_card_reopens_exact_other_offers_without_new_rng(self):
        for selected in (F0,F1):
            g=self.game();self.play(g,CARD);self.portable(g);self.select(g,selected)
            original=self.root(g).initial_entity_id;before=g._rng.getstate();self.play(g,selected,original)
            self.assertEqual({o.card_id for o in g.state.pending_choice.options},{F0,F1,F2}-{selected})
            self.assertEqual(g._rng.getstate(),before);other=self.portable(g);choice=self.select(g)
            self.select(other,choice);self.assertEqual(other.snapshot(),g.snapshot())
            self.assertEqual(self.root(g).status,'completed');self.assertEqual(g.state.players[1].mana,18)

    def test_preexisting_same_name_does_not_consume_original_physical_offer(self):
        g=self.game(hand=(CARD,F0));old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==F0)
        self.play(g,CARD);self.select(g,F0);original=self.root(g).initial_entity_id
        self.play(g,F0,old);self.assertIsNone(g.state.pending_choice);self.assertEqual(self.root(g).status,'armed')
        self.play(g,F0,original);self.assertIsNotNone(g.state.pending_choice);self.portable(g)

    def test_known_empty_rune_pool_retains_empty_record_without_rng(self):
        g=self.game(pool='empty');before=g._rng.getstate();self.play(g,CARD)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.root(g).status,'empty')
        self.assertEqual(g._rng.getstate(),before);self.portable(g)

    def test_eligible_unknown_runes_or_unadapted_definition_roll_back_before_sampling(self):
        for pool in ('unknown','unadapted'):
            g=self.game(pool=pool);before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,CARD)
            self.assertEqual(g.snapshot(),before)

    def test_selected_card_expires_at_original_turn_end(self):
        g=self.game();self.play(g,CARD);self.select(g,F0);original=self.root(g).initial_entity_id
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,F0,original)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.root(g).status,'expired');self.portable(g)

    def test_second_player_offer_is_private_and_invalid_selection_rolls_back(self):
        g=self.game(pid=2);self.play(g,CARD);q=g.state.pending_choice;before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,q.id,(q.options[0].id,)))
        self.assertEqual(g.snapshot(),before)
        visible=json.dumps(g.for_player(1).observe())+json.dumps(g.for_player(1).legal_actions())+json.dumps(g.player_events(1))
        for private in (F0,F1,F2,'runes_any','rng_state','resolution_frame'):self.assertNotIn(private,visible)
        self.select(g,F1);self.play(g,F1,self.root(g).initial_entity_id);self.portable(g)

    def test_saved_rune_query_cannot_be_replaced_or_loaded_under_old_schema(self):
        g=self.game();self.play(g,CARD)
        for rune in ('nature','blood'):
            saved=deepcopy(g.snapshot());changed=[]
            def walk(value):
                if isinstance(value,dict):
                    if 'runes_any'in value:
                        value['runes_any']={'tuple':[rune]}if isinstance(value['runes_any'],dict)else[rune]
                        changed.append(1)
                    for v in value.values():walk(v)
                elif isinstance(value,list):
                    for v in value:walk(v)
            walk(saved);self.assertTrue(changed)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry(self.pool,'reader'))
        saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.pool,'reader'))


if __name__=='__main__':unittest.main()
