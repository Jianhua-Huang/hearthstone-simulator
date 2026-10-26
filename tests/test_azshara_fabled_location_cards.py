"""Actual Azshara choices, physical locations, temporary generated spell material."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.azshara_fabled_location_cards import (ROOT,ZIN_BRANCH,WELL_BRANCH,
    WELL,WELL_UP,ZIN,ZIN_UP,POOL,register_azshara_fabled_location_cards,load_batch)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,TargetSpec,TriggerSpec,UseLocation,Zone)
from hs_sim.engine.card_creation import CardSpellRepeatGrant
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,GainArmor,InvokeBehavior,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fabled_decks import expand_fabled_cards
from hs_sim.engine.locations import ModifyLocation
from hs_sim.engine.model import CostSpec,SpellSchool
from hs_sim.engine.pools import GenerationContext,GenerateFromPool,FillHandFromPool,PoolCard,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.engine.zones import CardReference,FillHandWithCard,ModifyStoredCost
from hs_sim.targets import canonical_digest

P='azshara.test.'; FILL=P+'filler'; SPELL=P+'spell'; MISSING=P+'unknown'
VICTIM=P+'victim'; WATCH=P+'watch'


@lru_cache(maxsize=1)
def full_registry():return assembled_registry()


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in ('writer','reader')
    r=build_registry();register_azshara_fabled_location_cards(r)
    meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_card(CardDefinition(FILL,FILL,CardType.SPELL,metadata=meta))
    r.register_card(CardDefinition(VICTIM,VICTIM,CardType.MINION,attack=3,health=6,metadata=meta))
    r.register_behavior(SPELL,lambda c:(GainArmor(c.player_id,2),))
    generated=CardDefinition(SPELL,SPELL,CardType.SPELL,cost=1,on_play=SPELL,spell_school=SpellSchool.NATURE,
        metadata=replace(meta,collectible=True,max_copies=2))
    r.register_card(generated);r.register_pool_card(PoolCard.from_definition(generated))
    members=(PoolMember(SPELL),)
    if mode=='unknown':
        raw=replace(generated,id=MISSING,name=MISSING)
        r.register_pool_card(PoolCard.from_definition(raw));members+=(PoolMember(MISSING),)
    # This complete explicit fixture host pool is not the production Standard pool.
    r.register_pool(replace(next(iter(r.pools.values())),id=POOL,members=members,
        excluded_card_ids=(),complete=True))
    def spell(name,body,targeting):
        cid=P+name;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=meta))
    minions=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
    locations=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,),relation='friendly')
    hand_locations=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.LOCATION,),relation='friendly')
    spell('injure',lambda c:(Buff(c.target_id,2,3,source_id=c.source_id),Damage(c.target_id,2,c.source_id)),minions)
    spell('wear',lambda c:(ModifyLocation(c.target_id,-2,c.source_id),),locations)
    spell('cost',lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(delta=-2),source_id=c.source_id),),hand_locations)
    def fail(c):raise ResolutionError('Azshara deliberate failure')
    r.register_behavior(P+'fail',fail)
    if mode in ('board_wait','stored_wait','created_wait','created_fill','upgrade_fail'):
        event=('location_face_changed'if mode in ('board_wait','upgrade_fail')else
            'stored_card_transformed'if mode=='stored_wait'else'card_created')
        def watch(c):
            entity=c.state.entities.get(c.event.target_id)
            if entity is None:return ()
            if event=='card_created':
                if entity.card_id!=SPELL:return ()
                if entity.hand_lifetime is None or not any(a.kind=='card_spell_repeat' for a in entity.abilities):
                    raise ResolutionError('First observer saw incomplete temporary repeated spell material')
                if mode=='created_fill':return (FillHandWithCard(c.player_id,FILL,c.source_id),)
            if mode=='upgrade_fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,
            triggers=(TriggerSpec(event,WATCH),),metadata=meta))
    r.validate();r.freeze();return r


class AzsharaFabledLocationTests(unittest.TestCase):
    def game(self,hand=(ROOT,),board=(),*,deck=(),mode=None,enemy_board=(),enemy_hand=()):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,
            board=board+((WATCH,)if mode not in (None,'unknown')else()),deck=deck+(FILL,)*8,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,
            board=enemy_board,deck=(FILL,)*8,mana=50,max_mana=50,mana_cap=50)),seed=233211,
            generation_context=GenerationContext('local-2026-09-23','experimental')),registry('writer',mode))
    def ids(self,g,cid,pid=1,zone=Zone.BOARD):
        return [e.id for e in g.state.entities.values()if e.card_id==cid and e.controller==pid and e.zone==zone]
    def play(self,g,cid,target=None,branch=None):
        pid=g.state.active_player;eid=self.ids(g,cid,pid,Zone.HAND)[0]
        g.apply(PlayCard(pid,eid,target_id=target,branch_id=branch));return eid
    def use(self,g,cid,target=None):
        eid=self.ids(g,cid)[0];g.apply(UseLocation(1,eid,target));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode)
        self.assertIsNot(r,g.registry);s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','next_attachment_id','CardSpellRepeatGrant','CopyLocalState'):
                self.assertNotIn(key,wire)
        return other
    def test_a00_nine_complete_rows_fourteen_primary_faces_and_actual_family(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),14)
        self.assertEqual(sum(len(d[k])for k in ('cards','dependencies','evidence_only')),9)
        for key in ('cards','dependencies','evidence_only'):
            for row in d[key]:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        r=registry('writer');full=full_registry()
        for cid in (ROOT,ZIN_BRANCH,WELL_BRANCH,WELL,WELL_UP,ZIN,ZIN_UP):self.assertEqual(r.card(cid),full.card(cid))
        self.assertEqual(r.card(ROOT).metadata.classes,(CardClass.DRUID,))
        self.assertEqual(expand_fabled_cards((ROOT,),r),(ROOT,WELL,ZIN))
        self.assertTrue(r.card(ZIN_BRANCH).choice_only);self.assertFalse(r.card(ZIN_BRANCH).hand_playable)
        for cid in ('TIME_211t1te','TIME_211t2te'):self.assertNotIn(cid,r.cards)
    def test_a01_choose_zin_upgrades_own_three_zones_and_destroys_other_originals(self):
        g=self.game(hand=(ROOT,ZIN,WELL),board=(ZIN,WELL),deck=(ZIN,WELL),enemy_board=(ZIN,WELL),enemy_hand=(ZIN,WELL))
        originals={e.id:(e.card_id,e.zone)for e in g.state.entities.values()if e.controller==1 and e.card_id in (ZIN,WELL)}
        mid=self.play(g,ROOT,branch=ZIN_BRANCH);self.assertEqual(g.state.players[1].mana,45)
        for eid,(cid,zone)in originals.items():
            e=g.state.entities[eid];self.assertEqual(e.card_id,ZIN_UP if cid==ZIN else WELL)
            self.assertEqual(e.zone,zone if cid==ZIN else Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[mid].attack,g.state.entities[mid].health),(5,5))
        self.assertEqual(len(self.ids(g,ZIN,2)),1);self.assertEqual(len(self.ids(g,WELL,2)),1)
        self.assertEqual(len(self.ids(g,ZIN,2,Zone.HAND)),1);self.assertEqual(len(self.ids(g,WELL,2,Zone.HAND)),1);self.portable(g)
    def test_a02_choose_well_uses_opposite_real_branch(self):
        g=self.game(hand=(ROOT,WELL,ZIN),board=(WELL,ZIN),deck=(WELL,ZIN))
        self.play(g,ROOT,branch=WELL_BRANCH)
        for zone in (Zone.HAND,Zone.DECK,Zone.BOARD):
            self.assertEqual(len(self.ids(g,WELL_UP,zone=zone)),1);self.assertFalse(self.ids(g,ZIN,zone=zone))
        self.portable(g)
    def test_a03_no_companions_creates_no_runtime_bundle_or_rng_draw(self):
        g=self.game();before=g.snapshot()['rng_state'];self.play(g,ROOT,branch=ZIN_BRANCH)
        self.assertFalse([e for e in g.state.entities.values()if e.card_id in (WELL,WELL_UP,ZIN,ZIN_UP)])
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_a04_real_fandral_choose_both_executes_both_and_destroys_both(self):
        g=self.game(hand=(ROOT,WELL,ZIN),board=('OG_044',WELL,ZIN),deck=(WELL,ZIN))
        self.play(g,ROOT,branch=ROOT+':combined')
        for zone in (Zone.BOARD,Zone.HAND,Zone.DECK):
            for cid in (WELL,WELL_UP,ZIN,ZIN_UP):self.assertFalse(self.ids(g,cid,zone=zone))
        self.portable(g)
    def test_b00_upgrade_keeps_used_location_identity_durability_and_cooldown(self):
        g=self.game(board=(ZIN,VICTIM));loc=self.use(g,ZIN,self.ids(g,VICTIM)[0]);before=g.state.entities[loc]
        self.play(g,ROOT,branch=ZIN_BRANCH);after=g.state.entities[loc]
        self.assertEqual((after.card_id,after.durability,after.location_cooldown),(ZIN_UP,2,2))
        self.assertEqual(after.entered_order,before.entered_order);self.assertEqual(after.zone_epoch,before.zone_epoch+1);self.portable(g)
    def test_b01_stored_upgrade_preserves_real_hand_cost_attachment(self):
        g=self.game(hand=(P+'cost',ROOT,ZIN));eid=self.ids(g,ZIN,zone=Zone.HAND)[0]
        self.play(g,P+'cost',eid);old=g.state.entities[eid];attachments=tuple(old.enchantments)
        self.play(g,ROOT,branch=ZIN_BRANCH);e=g.state.entities[eid]
        self.assertEqual((e.card_id,e.cost_modifier),(ZIN_UP,-2));self.assertEqual(tuple(e.enchantments),attachments);self.portable(g)
    def test_b02_second_real_choice_destroys_already_upgraded_other_face(self):
        g=self.game(hand=(ROOT,ROOT,ZIN,WELL));self.play(g,ROOT,branch=ZIN_BRANCH)
        self.assertEqual(len(self.ids(g,ZIN_UP,zone=Zone.HAND)),1)
        self.play(g,ROOT,branch=WELL_BRANCH);self.assertFalse(self.ids(g,ZIN_UP,zone=Zone.HAND));self.portable(g)
    def test_c00_zin_current_copy_and_upgrade_double_actual_remaining_stats(self):
        for cid in (ZIN,ZIN_UP):
            with self.subTest(cid=cid):
                g=self.game(hand=(P+'injure',),board=(cid,VICTIM));target=self.ids(g,VICTIM)[0]
                self.play(g,P+'injure',target);source=g.state.entities[target]
                self.assertEqual((source.attack,source.health),(5,7));self.use(g,cid,target)
                other=next(e for e in g.state.entities.values()if e.card_id==VICTIM and e.zone==Zone.BOARD and e.id!=target)
                self.assertEqual((other.attack,other.health),(10,14)if cid==ZIN_UP else(5,7));self.portable(g)
    def test_c01_last_location_durability_frees_full_board_slot_before_copy(self):
        g=self.game(hand=(P+'wear',),board=(ZIN,)+(VICTIM,)*6);loc=self.ids(g,ZIN)[0]
        self.play(g,P+'wear',loc);self.assertEqual(g.state.entities[loc].durability,1)
        self.use(g,ZIN,self.ids(g,VICTIM)[0]);self.assertEqual(g.state.entities[loc].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.ids(g,VICTIM)),7);self.portable(g)
    def test_d00_base_well_fills_free_slots_with_temporary_single_cast_spells(self):
        g=self.game(hand=(FILL,)*8,board=(WELL,));self.use(g,WELL);ids=self.ids(g,SPELL,zone=Zone.HAND)
        self.assertEqual(len(ids),2)
        for eid in ids:
            e=g.state.entities[eid];self.assertEqual(e.hand_lifetime.expires_turn,1)
            self.assertFalse([a for a in e.abilities if a.kind=='card_spell_repeat'])
        self.play(g,SPELL);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(g.state.players[1].mana,49);g.apply(EndTurn(1))
        self.assertFalse(self.ids(g,SPELL,zone=Zone.HAND));self.portable(g)
    def test_d01_upgraded_well_installs_two_casts_before_normal_payment_and_expiry(self):
        g=self.game(hand=(FILL,)*8,board=(WELL_UP,));self.use(g,WELL_UP)
        self.assertEqual(len(self.ids(g,SPELL,zone=Zone.HAND)),2)
        self.play(g,SPELL);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
        self.assertEqual(g.state.players[1].mana,49)
        self.assertEqual(len([x for x in g.state.cast_history if x.card_id==SPELL]),2)
        g.apply(EndTurn(1));self.assertFalse(self.ids(g,SPELL,zone=Zone.HAND));self.portable(g)
    def test_d02_first_created_observer_sees_complete_repeat_and_temporary_waiting_material(self):
        g=self.game(hand=(FILL,)*8,board=(WELL_UP,),mode='created_wait');self.use(g,WELL_UP)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before)
        while other.state.pending_choice is not None:self.choose(other)
        self.assertEqual(len(self.ids(other,SPELL,zone=Zone.HAND)),2);self.portable(other)
    def test_d03_frozen_fill_count_keeps_complete_material_on_later_overflow(self):
        g=self.game(hand=(FILL,)*8,board=(WELL_UP,),mode='created_fill');self.use(g,WELL_UP)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len(self.ids(g,SPELL,zone=Zone.HAND)),1)
        burned=self.ids(g,SPELL,zone=Zone.GRAVEYARD);self.assertEqual(len(burned),1)
        e=g.state.entities[burned[0]];self.assertIsNotNone(e.hand_lifetime)
        self.assertTrue(any(a.kind=='card_spell_repeat'for a in e.abilities));self.portable(g)
    def test_d04_unknown_qualified_spell_is_not_trimmed_and_rolls_back_rng_and_activation(self):
        g=self.game(hand=(),board=(WELL_UP,),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g,WELL_UP)
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_d05_full_hand_keeps_rng_but_still_spends_real_location_use(self):
        g=self.game(hand=(FILL,)*10,board=(WELL_UP,));before=g.snapshot()['rng_state'];loc=self.use(g,WELL_UP)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(g.state.entities[loc].durability,2)
        self.assertFalse(self.ids(g,SPELL,zone=Zone.HAND));self.portable(g)
    def test_e00_board_upgrade_wait_preserves_queued_original_destruction_and_rolls_back_failed_choice(self):
        g=self.game(board=(ZIN,WELL),mode='board_wait');self.play(g,ROOT,branch=ZIN_BRANCH)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(self.ids(g,ZIN_UP));self.assertTrue(self.ids(g,WELL))
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.assertFalse(self.ids(other,WELL));self.portable(other)
    def test_e01_stored_upgrade_wait_preserves_remaining_originals_and_private_identity(self):
        g=self.game(hand=(ROOT,ZIN,WELL),deck=(ZIN,),mode='stored_wait');self.play(g,ROOT,branch=ZIN_BRANCH)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        while other.state.pending_choice is not None:self.choose(other)
        self.assertEqual(len(self.ids(other,ZIN_UP,zone=Zone.HAND)),1)
        self.assertEqual(len(self.ids(other,ZIN_UP,zone=Zone.DECK)),1)
        self.assertFalse(self.ids(other,WELL,zone=Zone.HAND));self.portable(other)
    def test_e02_late_upgrade_failure_restores_root_payment_both_locations_and_history(self):
        g=self.game(board=(ZIN,WELL),mode='upgrade_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ROOT,branch=ZIN_BRANCH)
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_f00_temporary_spell_fill_declarations_do_not_expand_unrelated_shapes(self):
        for kinds in ((CardType.SPELL,CardType.MINION),(CardType.WEAPON,),(CardType.LOCATION,)):
            with self.assertRaises(ValueError):GenerateFromPool(1,POOL,PoolQuery(kinds=kinds,collectible=True),source_id=1,temporary_until_turn=1)
        with self.assertRaises(ValueError):FillHandFromPool(GenerateFromPool(1,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True),source_id=1,cost=CostSpec(delta=-1)))
        with self.assertRaises(ValueError):GenerateFromPool(1,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True),source_id=1,temporary_until_turn=1,spell_repeat=CardSpellRepeatGrant())
        with self.assertRaises(ValueError):CreateTemporaryCard(1,SPELL,1,spell_repeat=True)


if __name__=='__main__':unittest.main()
