"""Real pool generation, a physical later-other-play gate and old turn clocks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.security_blind_spot_card import (BODY,CARD,GRANT,POOL_ID,QUERY,load_batch,
    register_security_blind_spot_card)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,
    PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec,UseHeroPower,UseLocation,Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,ChoiceOption,DestroyBatch,GainArmor,InvokeBehavior,
    RequestChoice,ReturnToHand,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_play_locks import play_error,validate_clock
from hs_sim.engine.model import OtherCardPlayLock
from hs_sim.engine.pools import (GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,
    resolve_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest

P='wing.test.'
GOOD=(P+'s1',P+'s2',P+'dual')
CTX=GenerationContext('wing-explicit-experiment','experimental')


def registry(mode=None,unknown=False):
    r=Registry('low-security-wing-native-tests-v1');register_security_blind_spot_card(r)
    r.register_card(CardDefinition(P+'hero','Hero',CardType.HERO,health=100))
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'fail',lambda c:(AddToHand(c.player_id,'missing.wing'),))
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'wait',wait)
    r.register_behavior(P+'generate',lambda c:(GenerateFromPool(c.player_id,POOL_ID,QUERY,
        source_id=c.source_id,minion_grant=GRANT),))
    r.register_behavior(P+'kill',lambda c:(DestroyBatch(tuple(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].kind==CardType.MINION),c.source_id),))
    r.register_behavior(P+'bounce',lambda c:(ReturnToHand(next(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id in GOOD)),))
    r.register_behavior(P+'power',lambda c:(CastSpell(c.player_id,P+'noop',c.source_id),Summon(c.player_id,P+'minion'),GainArmor(c.player_id,1)))
    r.register_card(CardDefinition(P+'power','Power',CardType.HERO_POWER,on_use=P+'power'))
    for name in ('noop','fail','wait','generate','kill','bounce'):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    r.register_card(CardDefinition(P+'minion','Other minion',CardType.MINION,attack=1,health=2))
    r.register_card(CardDefinition(P+'weapon','Other weapon',CardType.WEAPON,attack=1,durability=2))
    members=[]
    for cid,kind,classes,collectible in (
        (GOOD[0],CardType.MINION,(CardClass.SHAMAN,),True),
        (GOOD[1],CardType.MINION,(CardClass.SHAMAN,),True),
        (GOOD[2],CardType.MINION,(CardClass.SHAMAN,CardClass.MAGE),True),
        (P+'neutral',CardType.MINION,(CardClass.NEUTRAL,),True),
        (P+'mage',CardType.MINION,(CardClass.MAGE,),True),
        (P+'token',CardType.MINION,(CardClass.SHAMAN,),False),
        (P+'spell',CardType.SPELL,(CardClass.SHAMAN,),True)):
        card=CardDefinition(cid,cid,kind,cost=1,attack=2 if kind==CardType.MINION else 0,
            health=3 if kind==CardType.MINION else 0,on_play=P+'noop' if kind==CardType.SPELL else None,
            metadata=CardMetadata(collectible,classes,Rarity.COMMON))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card));members.append(cid)
    if unknown:
        cid=P+'unknown';r.register_pool_card(PoolCard(cid,CardType.MINION,1,
            CardMetadata(True,(CardClass.SHAMAN,),Rarity.COMMON)));members.append(cid)
    r.register_pool(PoolDefinition(POOL_ID,'wing-pool-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    def other(c):
        if mode=='kill_source':
            targets=tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
            return (DestroyBatch(targets,c.source_id),)
        cards=[c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in GOOD]
        if mode in ('copy','base') and cards:
            return (CopyCard(CardReference.capture(cards[0]),c.player_id,
                mode='current' if mode=='copy' else 'base',source_id=c.source_id),)
        return ()
    r.register_behavior(P+'other',other)
    r.register_card(CardDefinition(P+'other','Other Location',CardType.LOCATION,durability=3,on_use=P+'other'))
    if mode in ('created','fail_created'):
        def watch(c):
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.card_id not in GOOD:return ()
            if play_error(c.state,e) is None:raise ResolutionError('Missing gate before first creation notification')
            return wait(c) if mode=='created' else (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=10,
            triggers=(TriggerSpec('card_created',P+'watch'),)))
    return r


class SecurityBlindSpotTests(unittest.TestCase):
    def game(self,hand=(CARD,P+'noop'),*,board=(),mode=None,unknown=False):
        self.mode,self.unknown=mode,unknown
        if mode in ('created','fail_created'):board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(P+'hero',hand=hand,board=board,deck=(P+'noop',)*8,
            hero_power_card_id=P+'power',mana=20,max_mana=20,mana_cap=20),PlayerSetup(P+'hero',hand=(P+'noop',),
            deck=(P+'noop',)*8,mana=20,max_mana=20,mana_cap=20)),generation_context=CTX,seed=270),registry(mode,unknown))
    def play(self,g,cid=CARD,pid=1):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def use(self,g,eid=None):
        eid=eid or next(i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD)
        g.apply(UseLocation(1,eid));return eid
    def cards(self,g):return [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in GOOD]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode,self.unknown)
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('after_play_id','created_turn','OtherCardPlayLock','resolution_frame'):
                self.assertNotIn('"'+field+'"',public)
        return other
    def locked(self,g,eid):return play_error(g.state,g.state.entities[eid]) is not None

    def test_a00_complete_source_primary_faces_body_and_central_registration(self):
        row,=load_batch()['cards'];raw=row['record'];card=build_registry().card(CARD)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.kind,card.cost,card.durability,card.on_use),(CardType.LOCATION,1,3,BODY))
        self.assertEqual(len(load_batch()['official_observations']),2)

    def test_a01_paid_location_uses_one_charge_and_blocks_actual_and_listed_hand_play(self):
        g=self.game();source=self.play(g);self.assertEqual(g.state.players[1].mana,19);self.use(g,source)
        card,=self.cards(g);self.assertEqual(g.state.entities[source].durability,2);self.assertTrue(self.locked(g,card.id))
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==card.id for a in g.legal_actions()))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,card.id))
        self.assertEqual(g.snapshot(),saved);self.play(g,P+'noop');self.assertFalse(self.locked(g,card.id))
        g.apply(PlayCard(1,card.id));self.assertEqual(g.state.entities[card.id].zone,Zone.BOARD);self.portable(g)

    def test_a02_complete_pool_is_collectible_shaman_minions_including_dual_class(self):
        g=self.game();members=resolve_candidates(g.registry,CTX,POOL_ID,QUERY,current_class=CardClass.MAGE,source_card_id=CARD,player_id=1)
        self.assertEqual({m.card_id for m in members},set(GOOD));self.play(g);self.use(g)
        self.assertIn(self.cards(g)[0].card_id,GOOD)

    def test_a03_full_hand_burn_has_original_gate_before_normal_overflow(self):
        g=self.game((P+'noop',)*10,board=(CARD,));self.use(g)
        made=[e for e in g.state.entities.values() if e.card_id in GOOD]
        self.assertEqual(len(made),1);self.assertEqual(made[0].zone,Zone.GRAVEYARD)
        self.assertIsInstance(made[0].enchantments[0].hand_play_lock,OtherCardPlayLock)
        self.assertEqual(sum(e.kind=='card_burned' for e in g.events),1);self.portable(g)

    def test_a04_unknown_eligible_pool_member_rolls_back_rng_charge_and_generation(self):
        g=self.game(unknown=True);self.play(g);saved=g.snapshot()
        with self.assertRaises((UnsupportedDefinitionError,ResolutionError)):self.use(g)
        self.assertEqual(g.snapshot(),saved)

    def test_b00_later_minion_spell_weapon_or_location_play_unlocks_the_original(self):
        for cid in (P+'minion',P+'noop',P+'weapon',P+'other'):
            with self.subTest(cid=cid):
                g=self.game((CARD,cid));self.play(g);self.use(g);card=self.cards(g)[0].id
                self.play(g,cid);self.assertFalse(self.locked(g,card));g.apply(PlayCard(1,card))

    def test_b01_turns_draws_and_opponent_plays_do_not_unlock(self):
        g=self.game();self.play(g);self.use(g);card=self.cards(g)[0].id
        g.apply(EndTurn(1));self.play(g,P+'noop',pid=2);g.apply(EndTurn(2))
        self.assertTrue(self.locked(g,card));self.play(g,P+'noop');self.assertFalse(self.locked(g,card))

    def test_b02_power_automatic_cast_summon_and_other_location_use_do_not_unlock(self):
        g=self.game(board=(P+'other',));self.play(g);self.use(g);card=self.cards(g)[0].id
        n=len(g.state.play_history);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        other=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==P+'other')
        g.apply(UseLocation(1,other));self.assertEqual(len(g.state.play_history),n)
        self.assertTrue(self.locked(g,card));self.portable(g)

    def test_b03_card_already_in_flight_when_created_is_not_a_later_other_play(self):
        g=self.game((P+'generate',P+'noop'));source=self.play(g,P+'generate');card=self.cards(g)[0]
        self.assertTrue(g.state.play_history[-1].completed);self.assertTrue(self.locked(g,card.id))
        mark=next(e.hand_play_lock for e in card.enchantments if e.hand_play_lock is not None)
        self.assertEqual(mark.after_play_id,g.state.play_history[-1].id)
        self.assertEqual(g.state.play_history[-1].source_id,source);self.play(g,P+'noop');self.assertFalse(self.locked(g,card.id))

    def test_b04_other_play_must_commit_and_failed_wait_restores_same_locked_boundary(self):
        g=self.game((CARD,P+'wait'));self.play(g);self.use(g);card=self.cards(g)[0].id
        self.play(g,P+'wait');self.assertTrue(self.locked(g,card));saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(self.locked(g,card))

    def test_b05_failed_other_card_play_does_not_leave_an_unlock(self):
        g=self.game((CARD,P+'fail'));self.play(g);self.use(g);card=self.cards(g)[0].id;saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'fail')
        self.assertEqual(g.snapshot(),saved);self.assertTrue(self.locked(g,card))

    def test_b06_source_destroyed_by_nonplay_action_does_not_remove_the_gate(self):
        g=self.game(board=(P+'other',),mode='kill_source');source=self.play(g);self.use(g)
        card=self.cards(g)[0].id;other=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==P+'other')
        g.apply(UseLocation(1,other));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertTrue(self.locked(g,card));self.portable(g)

    def test_c00_current_copy_keeps_original_gate_and_base_copy_has_no_marker(self):
        for mode in ('copy','base'):
            with self.subTest(mode=mode):
                g=self.game(board=(P+'other',),mode=mode);self.play(g);self.use(g)
                original=self.cards(g)[0];other=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==P+'other')
                g.apply(UseLocation(1,other));first,copy=self.cards(g)
                self.assertTrue(self.locked(g,first.id));self.assertEqual(self.locked(g,copy.id),mode=='copy')
                if mode=='copy':
                    self.assertEqual(first.enchantments[0].hand_play_lock,copy.enchantments[0].hand_play_lock)
                    self.assertNotEqual(first.enchantments[0].id,copy.enchantments[0].id)
                self.portable(g)

    def test_c01_first_creation_wait_already_has_gate_and_restores_without_resampling(self):
        g=self.game(mode='created');self.play(g);self.use(g);card=self.cards(g)[0].id
        self.assertTrue(self.locked(g,card));other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.cards(g)),1)

    def test_c02_failed_creation_rolls_back_location_cost_rng_and_typed_gate(self):
        g=self.game(mode='fail_created');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),saved)

    def test_c03_private_gate_and_generated_identity_are_not_exposed_to_opponent(self):
        g=self.game();self.play(g);self.use(g);card=self.cards(g)[0]
        self.assertNotIn(card.card_id,json.dumps(g.for_player(2).observe()));self.portable(g)

    def test_c04_separate_location_uses_capture_independent_history_boundaries(self):
        g=self.game(board=(CARD,));initial=g.state.players[1].board[0];second=self.play(g)
        self.use(g,initial);first=self.cards(g)[0].id;self.play(g,P+'noop');self.assertFalse(self.locked(g,first))
        self.use(g,second);new=self.cards(g)[-1].id
        self.assertNotEqual(new,first);self.assertTrue(self.locked(g,new));self.assertFalse(self.locked(g,first))

    def test_d00_strict_gate_grant_and_same_codec_reject_invalid_and_mixed_recipes(self):
        g=self.game();self.play(g);self.use(g);mark=self.cards(g)[0].enchantments[0].hand_play_lock
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(mark)),mark)
        for args in ((True,0,1),(1,-1,1),(1,0,0)):
            with self.assertRaises(ValueError):OtherCardPlayLock(*args)
        with self.assertRaises(ValueError):CreatedMinionGrant(special='other_play_lock',attack=1)
        with self.assertRaises(ValueError):GenerateFromPool(1,POOL_ID,QUERY,count=2,source_id=1,minion_grant=GRANT)
        with self.assertRaises(ValueError):validate_clock(g.state,replace(mark,after_play_id=99999))

    def test_d01_rehashed_future_gate_and_missing_fields_are_rejected_on_restore(self):
        g=self.game();self.play(g);self.use(g);saved=json.loads(json.dumps(g.snapshot()));eid=self.cards(g)[0].id
        for field,value in (('after_play_id',999999),('created_turn',999999)):
            with self.subTest(field=field):
                bad=deepcopy(saved);bad['state']['entities'][str(eid)]['enchantments'][0]['hand_play_lock'][field]=value
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        bad=deepcopy(saved);bad['schema_version']=442
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        bad=deepcopy(saved);del bad['state']['entities'][str(eid)]['enchantments'][0]['hand_play_lock']['created_turn']
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_d02_normal_return_resets_gate_and_frozen_death_retains_valid_original_material(self):
        for command in ('kill','bounce'):
            with self.subTest(command=command):
                g=self.game((CARD,P+'noop',P+command));self.play(g);self.use(g);eid=self.cards(g)[0].id
                self.play(g,P+'noop');g.apply(PlayCard(1,eid));self.play(g,P+command)
                if command=='kill':
                    death=next(d for d in g.state.death_history if d.entity_id==eid)
                    self.assertIsInstance(next(e.hand_play_lock for e in death.enchantments if e.hand_play_lock is not None),OtherCardPlayLock)
                else:
                    self.assertEqual(g.state.entities[eid].zone,Zone.HAND)
                    self.assertFalse(any(e.hand_play_lock is not None for e in g.state.entities[eid].enchantments))
                self.portable(g)


if __name__=='__main__':unittest.main()
