"""Odd Map uses printed Beast attack and retains its original private choices."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_odd_map_cards import CARD,BODY,POOL,load_batch,register_native_odd_map_cards
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,
    PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,TargetSpec,Zone)
from hs_sim.engine.cross_zone import MinionScope,minion_references
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,zone_candidates

P='k169.'
HERO,ONE,DUAL,ALL,EVEN,ZERO,DRAGON,FOREIGN,MISSING,UNKNOWN,BUFF=(P+x for x in
    ('hero','one','dual','all','even','zero','dragon','foreign','missing','unknown','buff'))
CONTEXT=GenerationContext('k169-native-fixture','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('beast',))


@lru_cache(maxsize=None)
def registry(pool='all',role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent immutable registry role required')
    r=Registry('odd-map-'+pool);register_native_odd_map_cards(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=replace(META,collectible=False,classes=(CardClass.HUNTER,),tribes=())))
    specs=((ONE,1,('beast',)),(DUAL,5,('dragon','beast')),(ALL,3,('all',)),
           (EVEN,2,('beast',)),(ZERO,0,('beast',)),(DRAGON,3,('dragon',)),(FOREIGN,3,('beast',)))
    for cid,attack,tribes in specs:
        card=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=4,
            metadata=replace(META,tribes=tribes,classes=(CardClass.MAGE,)if cid==FOREIGN else(CardClass.NEUTRAL,)))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=tuple(cid for cid,_,_ in specs)if pool!='empty'else(EVEN,ZERO,DRAGON,FOREIGN)
    if pool in ('unadapted','unknown','foreign_unknown'):
        cid=MISSING if pool=='unadapted'else UNKNOWN
        r.register_pool_card(PoolCard(cid,CardType.MINION,1,
            replace(META,classes=(CardClass.MAGE,)if pool=='foreign_unknown'else(CardClass.NEUTRAL,)),
            attack=3 if pool=='unadapted'else None))
        members+=(cid,)
    r.register_pool(PoolDefinition(POOL,'v1',CONTEXT.target_id,CONTEXT.mode,
                                  tuple(PoolMember(i)for i in members),complete=True))
    r.register_behavior(P+'buff',lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),
                                                        attack=1,source_id=c.source_id),))
    r.register_card(CardDefinition(BUFF,BUFF,CardType.SPELL,on_play=P+'buff',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly'),
        metadata=replace(META,collectible=False,tribes=())))
    r.validate();r.freeze();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class OddMapTests(unittest.TestCase):
    def game(self,pool='all',pid=1,hand=(CARD,)):
        self.pool,self.pid=pool,pid
        setup=tuple(PlayerSetup(HERO,hand=hand if p==pid else (),deck=(EVEN,)*8,
            mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(setup,active_player=pid,seed=169,generation_context=CONTEXT),registry(pool))
    def play(self,g,cid,target=None,entity=None):
        e=g.state.entities[entity]if entity is not None else next(g.state.entities[i]
            for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,target_id=target,
                        position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None))
        return e.id
    def choose(self,g,cid=None):
        q=g.state.pending_choice;o=next(x for x in q.options if cid is None or x.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id
    def root(self,g):return g.state.hand_choice_followups[-1]
    def portable(self,g):
        reader=registry(self.pool,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_original_card_and_both_full_primary_faces_are_pinned(self):
        from tools.card_batch import check_face
        data=load_batch();raw=data['cards'][0]['record'];card=registry().card(CARD)
        self.assertEqual((card.cost,card.metadata.classes,card.on_play,card.spell_school),
                         (1,(CardClass.HUNTER,),BODY,None))
        self.assertEqual(len(data['official_observations']),2)
        for o in data['official_observations']:check_face(raw,o['face'],o['locale'])

    def test_paid_entry_includes_odd_dual_and_all_beasts_excludes_zero_even_foreign_and_other_tribe(self):
        g=self.game();self.play(g,CARD);root=self.root(g)
        self.assertEqual(root.request.query.attack_parity,'odd')
        self.assertEqual({x.card_id for x in root.available_pool},{ONE,DUAL,ALL})
        self.assertEqual({x.card_id for x in root.offers},{ONE,DUAL,ALL})
        self.assertEqual(g.state.players[1].mana,19);self.portable(g)

    def test_current_hand_buff_does_not_change_printed_filter_or_original_reward_offer(self):
        g=self.game(hand=(CARD,BUFF));self.play(g,CARD);self.choose(g,ONE);original=self.root(g).initial_entity_id
        self.play(g,BUFF,target=original);self.assertEqual(g.state.entities[original].attack,2)
        query=PoolQuery(kinds=(CardType.MINION,),attack_parity='odd')
        physical=minion_references(g.state,g.registry,1,MinionScope(zones=(Zone.HAND,),query=query))
        self.assertEqual({x.entity_id for x in physical},{original})
        self.assertEqual({x.entity_id for x in zone_candidates(Resolution(g),1,Zone.HAND,query,1)},{original})
        before=g._rng.getstate();self.play(g,ONE,entity=original)
        self.assertEqual({x.card_id for x in g.state.pending_choice.options},{DUAL,ALL})
        self.assertEqual(g._rng.getstate(),before);other=self.portable(g);choice=self.choose(g)
        self.choose(other,choice);self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(self.root(g).status,'completed')

    def test_both_real_choice_boundaries_restore_clone_replay_and_keep_original_rng(self):
        g=self.game();self.play(g,CARD);self.portable(g);self.choose(g,DUAL)
        original=self.root(g).initial_entity_id;before=g._rng.getstate();self.play(g,DUAL,entity=original)
        self.assertEqual({x.card_id for x in g.state.pending_choice.options},{ONE,ALL})
        self.assertEqual(g._rng.getstate(),before);self.portable(g);self.choose(g,ALL);self.portable(g)

    def test_unknown_eligible_attack_and_unimplemented_odd_candidates_fail_atomically(self):
        for pool in ('unknown','unadapted'):
            g=self.game(pool);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,CARD)
            self.assertEqual(g.snapshot(),saved)
        g=self.game('foreign_unknown');self.play(g,CARD)
        self.assertNotIn(UNKNOWN,{x.card_id for x in self.root(g).available_pool});self.portable(g)

    def test_known_empty_odd_beast_pool_retains_empty_root_without_randomness(self):
        g=self.game('empty');before=g._rng.getstate();self.play(g,CARD)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.root(g).status,'empty')
        self.assertEqual(g._rng.getstate(),before);self.portable(g)

    def test_second_player_private_offers_and_wrong_player_selection_roll_back(self):
        g=self.game(pid=2);self.play(g,CARD);q=g.state.pending_choice;saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,q.id,(q.options[0].id,)))
        self.assertEqual(g.snapshot(),saved)
        public=json.dumps(g.for_player(1).observe())+json.dumps(g.for_player(1).legal_actions())+json.dumps(g.player_events(1))
        for private in (ONE,DUAL,ALL,'attack_parity','resolution_frame','rng_state'):self.assertNotIn(private,public)
        self.choose(g,ONE);self.play(g,ONE,entity=self.root(g).initial_entity_id);self.portable(g)

    def test_saved_query_parity_cannot_change_even_after_snapshot_rehash(self):
        g=self.game();self.play(g,CARD)
        for parity in ('even','not-a-parity'):
            saved=deepcopy(g.snapshot());changed=[]
            def walk(value):
                if isinstance(value,dict):
                    if 'attack_parity'in value:value['attack_parity']=parity;changed.append(1)
                    for v in value.values():walk(v)
                elif isinstance(value,list):
                    for v in value:walk(v)
            walk(saved);self.assertTrue(changed)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry(self.pool,'reader'))


if __name__=='__main__':unittest.main()
