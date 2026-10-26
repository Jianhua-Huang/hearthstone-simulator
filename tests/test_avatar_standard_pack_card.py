"""Actual Avatar and complete explicit experimental pack domains."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.avatar_standard_pack_card import CARD, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.card_packs import (OPENED, STEP, FINISHED, StandardPackProfile, pack_candidates)
from hs_sim.engine.effects import ChangeControl, ChoiceOption, Damage, Destroy, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash
from tools.card_batch import check_face

P = 'fixture.standard_pack.'
UNKNOWN = P + 'unimplemented'
UNIT, SPELL, WEAPON, LOCATION, HERO, POWER, MOVE, KILL, LETHAL, TARGET, WATCH, TRIGGER = (
    P+x for x in ('unit','spell','weapon','location','hero','power','move','kill','lethal','target','watch','trigger'))
CTX = GenerationContext('avatar-complete-explicit-pack-experiment','experimental')
MIXED = (UNIT,SPELL,WEAPON,LOCATION,HERO)


@lru_cache(maxsize=None)
def fixture(mode='normal', pool='mixed'):
    r=build_registry()
    def fail(c): raise ResolutionError('Explicit pack observer or forbidden physical body')
    def source(c): return next(e for e in c.state.entities.values() if e.card_id==CARD)
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'move',lambda c:(ChangeControl(source(c).id,2),))
    r.register_behavior(P+'kill',lambda c:(Destroy(source(c).id,c.source_id),))
    r.register_behavior(P+'lethal',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),))
    r.register_behavior(P+'target',lambda c:(Damage(c.target_id,1,c.source_id),))
    def watch(c):
        if any(eid is not None and c.state.entities[eid].card_id==UNIT for eid in (c.event.source_id,c.event.target_id)):
            if mode=='fail': raise ResolutionError('Explicit pack summon observer failure')
            if mode=='wait':return(RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(UNIT,'Explicit pack minion',CardType.MINION,cost=3,attack=1,health=20,
        battlecry=P+'fail',combo=P+'fail',keywords=(Keyword.COMBO,),metadata=metadata()))
    r.register_card(CardDefinition(SPELL,'Explicit pack spell',CardType.SPELL,cost=3,on_play=P+'armor',metadata=metadata()))
    r.register_card(CardDefinition(WEAPON,'Explicit pack weapon',CardType.WEAPON,cost=3,attack=2,durability=3,
        battlecry=P+'fail',metadata=metadata()))
    r.register_card(CardDefinition(LOCATION,'Explicit pack location',CardType.LOCATION,cost=3,durability=2,
        on_use=P+'fail',metadata=metadata()))
    r.register_card(CardDefinition(POWER,'Explicit installed power',CardType.HERO_POWER,cost=2,on_use=P+'armor',
        metadata=metadata(CardClass.WARLOCK,collectible=False)))
    r.register_card(CardDefinition(HERO,'Explicit pack hero',CardType.HERO,cost=3,health=30,hero_card=True,
        hero_armor=5,initial_hero_power=POWER,battlecry=P+'fail',metadata=metadata(CardClass.WARLOCK)))
    for cid,name in ((MOVE,'move'),(KILL,'kill'),(LETHAL,'lethal')):
        r.register_card(CardDefinition(cid,name,CardType.SPELL,cost=3,on_play=P+name,metadata=metadata()))
    r.register_card(CardDefinition(TARGET,'Explicit directed pack spell',CardType.SPELL,cost=3,
        on_play=P+'target',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=metadata()))
    r.register_card(CardDefinition(WATCH,'Explicit observer',CardType.MINION,health=30,
        triggers=(TriggerSpec('minion_summoned',P+'watch'),)))
    def trigger(c):return(TriggerBattlecry(MinionReference.capture(source(c)),c.source_id),)
    r.register_behavior(P+'trigger',trigger)
    r.register_card(CardDefinition(TRIGGER,'Explicit Battlecry trigger',CardType.MINION,health=1,battlecry=P+'trigger'))
    for cid in (*MIXED,MOVE,KILL,LETHAL,TARGET):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    # Keep this a genuinely missing definition as real card coverage expands.
    r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,metadata()))
    members={'mixed':MIXED,'minion':(UNIT,),'spell':(SPELL,),'weapon':(WEAPON,),'location':(LOCATION,),
        'hero':(HERO,),'move':(MOVE,UNIT),'kill':(KILL,UNIT),'lethal':(LETHAL,),'target':(TARGET,),
        'unknown':(UNKNOWN,),'empty':(),'incomplete':(UNIT,)}[pool]
    r.register_pool(PoolDefinition('constructed.standard_pack','explicit-pack-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=pool!='incomplete'))
    r.validate()
    return r


def seed_for(pool, predicate):
    r=fixture(pool=pool);_,members=pack_candidates(r,CTX,r._standard_pack_profiles[CARD])
    for seed in range(10000):
        drawn=sample_candidates(Random(seed),members,5,replacement=True)
        if predicate(drawn):return seed
    raise AssertionError('No deterministic seed for the complete experimental pack domain')


class AvatarStandardPackTests(unittest.TestCase):
    def game(self, *, pool='mixed', mode='normal', hand=(), board=(), seed=991, context=CTX):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=(CARD,)+hand,board=((WATCH,)if mode!='normal'else())+board,
                deck=(UNIT,)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(UNIT,)*12,mana=10,max_mana=10)),
            seed=seed,generation_context=context),fixture(mode,pool))
    def play(self,g,cid=CARD):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='normal',pool='mixed'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture.__wrapped__(mode,pool)
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        return saved

    def test_full_core_face_and_explicit_independent_pack_contract_are_pinned(self):
        d=load_batch();raw=d['cards'][0]['record'];r=fixture()
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(9,5,5))
        self.assertEqual(len(d['official_observations']),2)
        for obs in d['official_observations']:check_face(raw,obs['face'],obs['locale'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        self.assertEqual(r._standard_pack_profiles[CARD],StandardPackProfile(CARD))
        self.assertEqual(len(pack_candidates(r,CTX,r._standard_pack_profiles[CARD])[1]),5)

    def test_all_five_native_kinds_execute_without_extra_payment_or_physical_battlecries(self):
        seed=seed_for('mixed',lambda values:set(values)==set(MIXED));g=self.game(seed=seed)
        source=self.play(g);p=g.state.players[1]
        self.assertEqual(p.mana,1);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.cast_history[0].card_id,SPELL)
        self.assertEqual(g.state.entities[p.weapon_id].card_id,WEAPON)
        self.assertEqual(g.state.entities[p.hero_id].card_id,HERO)
        self.assertEqual(g.state.entities[p.hero_power_id].card_id,POWER)
        self.assertEqual(g.state.entities[p.hero_id].armor,6)
        self.assertEqual({g.state.entities[e].card_id for e in p.board},{CARD,UNIT,LOCATION})
        self.assertEqual(len([e for e in g.events if e.kind==STEP]),5)
        self.assertEqual(len([e for e in g.events if e.kind==FINISHED]),1);self.portable(g)

    def test_full_hand_does_not_reduce_pack_or_create_fake_hand_entries(self):
        g=self.game(pool='minion',hand=(SPELL,)*9);self.play(g)
        self.assertEqual(len(g.state.players[1].hand),9)
        self.assertEqual(sum(g.state.entities[e].card_id==UNIT for e in g.state.players[1].board),5)
        self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(any(e.kind in ('card_added_to_hand','card_burned')for e in g.events))
        self.portable(g,pool='minion')

    def test_full_board_consumes_each_failed_minion_or_location_attempt_without_skipping_slots(self):
        for pool in ('minion','location'):
            with self.subTest(pool=pool):
                g=self.game(pool=pool,board=(UNIT,)*6);self.play(g)
                self.assertEqual(len(g.state.players[1].board),7)
                self.assertEqual(len([e for e in g.events if e.kind==STEP]),5)
                self.assertEqual(len([e for e in g.events if e.kind==FINISHED]),1)

    def test_pack_spells_use_real_automatic_casts_and_pay_no_child_cost(self):
        g=self.game(pool='spell');self.play(g)
        self.assertEqual(len(g.state.cast_history),5)
        self.assertTrue(all(c.origin=='effect'and c.completed for c in g.state.cast_history))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.assertEqual(g.state.players[1].mana,1);self.assertEqual(len(g.state.play_history),1)

    def test_no_legal_target_keeps_each_original_failed_cast_and_continues(self):
        g=self.game(pool='target');self.play(g)
        self.assertEqual(len(g.state.cast_history),5)
        self.assertTrue(all(c.failure is not None for c in g.state.cast_history))
        self.assertEqual(len([e for e in g.events if e.kind==FINISHED]),1);self.portable(g,pool='target')

    def test_later_original_pack_cards_follow_issuer_current_controller(self):
        seed=seed_for('move',lambda values:values==(MOVE,UNIT,UNIT,UNIT,UNIT));g=self.game(pool='move',seed=seed)
        source=self.play(g);self.assertEqual(g.state.entities[source].controller,2)
        steps=[e for e in g.events if e.kind==STEP]
        self.assertEqual([e.player_id for e in steps],[1,2,2,2,2])
        self.assertEqual(sum(g.state.entities[e].card_id==UNIT for e in g.state.players[2].board),4)
        self.assertEqual(g.state.players[1].mana,1);self.portable(g,pool='move')

    def test_accepted_pack_continues_after_original_issuer_dies(self):
        seed=seed_for('kill',lambda values:values==(KILL,UNIT,UNIT,UNIT,UNIT));g=self.game(pool='kill',seed=seed)
        source=self.play(g);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(sum(g.state.entities[e].card_id==UNIT for e in g.state.players[1].board),4)
        self.assertEqual(len([e for e in g.events if e.kind==FINISHED]),1);self.portable(g,pool='kill')

    def test_missing_incomplete_empty_and_unknown_eligible_pack_domain_fail_transactionally(self):
        for pool,context in (('mixed',None),('incomplete',CTX),('empty',CTX),('unknown',CTX)):
            with self.subTest(pool=pool,context=context):
                g=self.game(pool=pool,context=context);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),saved)

    def test_source_and_pool_metadata_do_not_define_shop_probabilities_or_a_default_pack(self):
        r=build_registry();self.assertFalse(any(p.id=='constructed.standard_pack'for p in r.pools.values()))
        with self.assertRaises(ValueError):StandardPackProfile(CARD,'constructed.cards')
        with self.assertRaises(ValueError):StandardPackProfile(CARD,version='invented-rarity-weight-v1')

    def test_pending_summon_reaction_restores_one_original_pack_and_next_occurrence(self):
        g=self.game(pool='minion',mode='wait');self.play(g);saved=self.portable(g,'wait','minion')
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        while g.state.pending_choice is not None:self.choose(g,'ok')
        self.assertEqual(len([e for e in g.events if e.kind==OPENED]),1)
        self.assertEqual(len([e for e in g.events if e.kind==STEP]),5)
        self.assertEqual(len([e for e in g.events if e.kind==FINISHED]),1)

    def test_observer_failure_rolls_back_pack_rng_payment_allocations_and_history(self):
        g=self.game(pool='minion',mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_terminal_first_card_interrupts_unplayed_occurrences_without_extra_casts(self):
        g=self.game(pool='lethal');self.play(g)
        self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(len([e for e in g.events if e.kind==STEP]),1)
        self.assertFalse(any(e.kind==FINISHED for e in g.events));self.portable(g,pool='lethal')

    def test_indirect_battlecry_opens_one_new_pack_without_another_source_payment(self):
        g=self.game(pool='minion',hand=(TRIGGER,));self.play(g)
        self.play(g,TRIGGER)
        self.assertEqual(len([e for e in g.events if e.kind==OPENED]),2)
        self.assertEqual(len([e for e in g.events if e.kind==STEP]),10)
        self.assertEqual(g.state.players[1].mana,1)

    def test_private_pack_domain_rng_and_unplayed_cards_never_enter_player_dto(self):
        g=self.game(pool='minion',mode='wait');self.play(g)
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for private in (OPENED,STEP,'rng_before','pool_version','opening_id'):self.assertNotIn(private,text)

    def test_rehashed_cropped_domain_weights_or_original_draw_reject(self):
        g=self.game(pool='minion',mode='wait');self.play(g);saved=g.snapshot()
        for mode in ('domain','weights','draw'):
            bad=deepcopy(saved);event=next(e for e in bad['events']if e['kind']==OPENED)
            if mode=='domain':event['data']['candidates'].clear()
            elif mode=='weights':event['data']['candidates'][0][1]+=1
            else:event['data']['drawn'][0]=SPELL
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait','minion'))

    def test_waiting_original_cursor_cannot_be_removed_duplicated_or_borrowed(self):
        g=self.game(pool='minion',mode='wait');self.play(g);saved=g.snapshot()
        def edit(value,mode):
            if isinstance(value,list):
                for index,row in enumerate(value):
                    if isinstance(row,dict)and row.get('type','').endswith('.PlayStandardPackSlot'):
                        if mode=='remove':value.pop(index)
                        elif mode=='duplicate':value.insert(index,deepcopy(row))
                        else:row['fields']['opening_id']+=1
                        return True
                    if edit(row,mode):return True
            elif isinstance(value,dict):
                for row in value.values():
                    if edit(row,mode):return True
            return False
        for mode in ('remove','duplicate','borrow'):
            bad=deepcopy(saved);self.assertTrue(edit(bad,mode))
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait','minion'))
