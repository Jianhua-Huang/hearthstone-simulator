"""Real treasure faces run through ordinary, explicitly declared diagnostic domains."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import excavate_shared_treasures as native
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec, UseLocation)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, Damage, Destroy, DestroyBatch, GainArmor, InvokeBehavior, Silence)
from hs_sim.engine.model import CardMetadata, Rarity, TargetSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k608.'
NOOP,WOUND,KILL,ALL,SILENCE,POWER,FAIL,FILL=(P+x for x in('noop','wound','kill','all','silence','power','fail','fill'))
A,D,SP,Q,FOREIGN=('a','d','spell','other','foreign')
IDS={cost:{name:P+name+str(cost)for name in(A,D,SP,Q,FOREIGN)}for cost in(2,3,5)}
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())
DISCOVER={native.FOOL:2,native.CHUNK:3,native.CRYSTAL:5}


def context(mode='normal'): return GenerationContext(P+'complete-diagnostic-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,3),))
    r.register_behavior(WOUND,lambda c:(Damage(c.target_id,6,c.source_id),))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_behavior(ALL,lambda c:(DestroyBatch(tuple(i for p in(1,2)for i in c.state.players[p].board),c.source_id),))
    r.register_behavior(SILENCE,lambda c:(Silence(c.target_id),))
    for cid in(NOOP,WOUND,KILL,ALL,SILENCE):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            **({'targeting':TargetSpec()}if cid==WOUND else {'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in(KILL,SILENCE)else {})))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,attack=1,health=12,spell_damage=2,metadata=META))
    pool=[]
    for cost,ids in IDS.items():
        for name,cid in ids.items():
            kind=CardType.MINION if name in(A,D)else CardType.SPELL
            meta=replace(META,classes=(CardClass.PALADIN,)if name==FOREIGN else (CardClass.MAGE,)if name==SP else (CardClass.NEUTRAL,))
            # Two neutral minions and one Mage spell comprise each three-card class Discover domain.
            if name==Q: continue
            r.register_card(CardDefinition(cid,cid,kind,cost=cost,attack=1 if kind==CardType.MINION else 0,
                health=12 if kind==CardType.MINION else 0,on_play=P+'armor'if kind==CardType.SPELL else None,metadata=meta))
            r.register_pool_card(PoolCard.from_definition(r.card(cid)));pool.append(cid)
    if mode=='unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.MINION,2,META));pool.append(P+'unknown')
    r.register_pool(PoolDefinition(native.POOL,P+'whole-v1',context(mode).target_id,'experimental',
        tuple(PoolMember(cid)for cid in pool),complete=True))
    def fail(c): raise ResolutionError('K608 deliberate damage reaction failure')
    r.register_behavior(P+'fault',fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None:return ()
        if c.source.card_id==FAIL and source.card_id==native.COLLAPSE:
            return(InvokeBehavior(P+'fault',c.source_id,c.player_id),)
        if c.source.card_id==FILL and source.card_id in DISCOVER:
            return(AddToHand(c.player_id,NOOP,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid,event in((FAIL,'damage_dealt'),(FILL,'card_committed')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,metadata=META,triggers=(TriggerSpec(event,P+'watch'),)))
    r.validate();return r


class ExcavateSharedTreasureTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,board=(),enemy_board=(),enemy_hand=(),deck=None,player=1,mode='normal'):
        self.mode=mode
        if deck is None:deck=(NOOP,)*5
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else enemy_hand,
            board=board if p==player else enemy_board,deck=deck if p==player else (NOOP,)*5,
            mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=608,generation_context=context(mode)),registry(mode))

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def paid(self,g,cid,target=None,player=1):
        e=self.entity(g,cid,player);amount=quote_cost(g.state,g.registry,e).amount;mana=g.state.players[player].mana
        source=self.play(g,cid,target,player)
        self.assertEqual(g.state.players[player].mana,mana-amount)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,amount))
        return source

    def test_full_twenty_six_records_fifty_two_primary_faces_and_collection_roles(self):
        d=native.load_batch();rows={r['record']['id']:r for k in('cards','existing_dependencies','evidence_only')for r in d[k]}
        self.assertEqual((len(rows),len(d['official_observations'])),(26,52))
        for observation in d['official_observations']:
            batch.check_face(rows[observation['card_id']]['record'],observation['face'],observation['locale'])
        r=registry()
        for cid in native.CARDS:
            raw=rows[cid]['record'];c=r.card(cid)
            self.assertFalse(c.metadata.collectible);self.assertEqual(c.cost,raw['cost'])
            self.assertEqual(c.metadata.tribes,tuple(rows[cid]['metadata']['tribes']))
            self.assertEqual(c.durability if c.kind==CardType.LOCATION else c.health,raw['health']or 0)
        self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_complete_local_inventory_six_each_and_seven_classes_without_binding_sample_profile(self):
        d=native.load_batch();inventory=d['inventory'];self.assertEqual(len(inventory['member_ids']),25)
        self.assertEqual([len(t['member_ids'])for t in inventory['shared_tiers']],[6]*3)
        self.assertTrue(all(t['weights']==[1]*6 and not t['excluded_card_ids']for t in inventory['shared_tiers']))
        self.assertEqual(len(inventory['class_rewards']),7)
        self.assertEqual(set(inventory['member_ids']),set(native.CARDS+native.EXISTING+('DEEP_999t3',)))
        self.assertFalse(inventory['runtime_bound']);self.assertFalse(d['formal_pool_complete'])
        self.assertEqual(list(registry().excavation_profiles),[('excavate','local-2026-09-23','experimental')])
        self.assertFalse(next(iter(registry().excavation_profiles.values())).complete)
        # The original treasure batch did not register the producer. Later
        # native registration adds it without changing this old sample profile.
        before_producer=batch.registration_prefix(build_registry,
            'hs_sim.cards.excavate_local_host.register_cryopreservation',lambda registry:None)
        self.assertNotIn('WW_009',before_producer.cards)
        self.assertIn('WW_009',registry().cards)
        from hs_sim.cards.shard_original_remainders import register_shard_original_remainders
        original=batch.registration_prefix(build_registry,'hs_sim.cards.shard_original_remainders.register_shard_original_remainders',register_shard_original_remainders)
        self.assertNotIn('DEEP_999t3',original.cards)
        for row in d['existing_dependencies']:
            self.assertEqual(batch.canonical(asdict(registry().card(row['record']['id']))),row['definition_sha256'])

    def test_original_keyword_bodies_are_not_blank_stat_proxies(self):
        r=registry()
        self.assertEqual(r.card(native.TROGG).keywords,(Keyword.RUSH,))
        self.assertEqual(r.card(native.LIVING).keywords,(Keyword.TAUNT,))
        self.assertEqual(r.card(native.MOLE).keywords,(Keyword.TAUNT,Keyword.REBORN,Keyword.ELUSIVE))
        self.assertIsNotNone(r.card(native.CLUSTER).triggers[0].end_turn)

    def test_heartblossom_buffs_real_friendly_then_random_spell_damage_respects_spell_power(self):
        g=self.game((native.FLOWER,),board=(IDS[2][A],POWER),enemy_board=(IDS[2][D],))
        target=self.entity(g,IDS[2][A],zone='board');enemy=self.entity(g,IDS[2][D],2,'board')
        self.paid(g,native.FLOWER,target.id)
        target=g.state.entities[target.id];enemy=g.state.entities[enemy.id]
        self.assertEqual((target.attack,target.health),(3,14));self.assertEqual(enemy.health,8)
        self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_heartblossom_empty_enemy_pool_still_buffs_without_rng_and_rejects_enemy_target(self):
        g=self.game((native.FLOWER,),board=(IDS[2][A],));target=self.entity(g,IDS[2][A],zone='board')
        rng=g.snapshot()['rng_state'];self.play(g,native.FLOWER,target.id)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.entities[target.id].attack,3)
        h=self.game((native.FLOWER,),enemy_board=(IDS[2][A],));before=h.snapshot()
        with self.assertRaises(IllegalAction):self.play(h,native.FLOWER,self.entity(h,IDS[2][A],2,'board').id)
        self.assertEqual(h.snapshot(),before)

    def test_water_restores_character_then_draws_original_physical_top_card(self):
        g=self.game((WOUND,native.WATER),deck=(IDS[2][SP],));hero=self.hero(g,1)
        top=g.state.players[1].deck[0];self.play(g,WOUND,hero.id);self.assertEqual(self.hero(g,1).health,24)
        self.paid(g,native.WATER,hero.id)
        self.assertEqual(self.hero(g,1).health,27);self.assertIn(top,g.state.players[1].hand)
        self.assertFalse(g.state.players[1].deck);self.assertFalse(g.state.excavation_history);self.portable(g)

    def test_water_full_health_still_draws_and_empty_deck_uses_ordinary_fatigue(self):
        g=self.game((native.WATER,),deck=());self.play(g,native.WATER,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(self.hero(g,1).health,29)

    def test_collapse_hits_all_enemy_characters_with_spell_damage_both_seats(self):
        for p in(1,2):
            g=self.game((native.COLLAPSE,),board=(POWER,),enemy_board=(IDS[2][A],IDS[2][D]),player=p)
            self.paid(g,native.COLLAPSE,player=p)
            self.assertEqual(self.hero(g,3-p).health,25)
            self.assertEqual([g.state.entities[i].health for i in g.state.players[3-p].board],[7,7])
            self.assertEqual(self.hero(g,p).health,30)

    def test_cluster_only_triggers_owner_end_and_effect_damage_ignores_spell_power(self):
        g=self.game(board=(native.CLUSTER,POWER),enemy_board=(IDS[2][A],))
        g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,28)
        self.assertEqual(self.entity(g,IDS[2][A],2,'board').health,10)
        g.apply(EndTurn(2));self.assertEqual(self.hero(g,2).health,28);self.portable(g)

    def test_cluster_silence_removes_actual_end_body(self):
        g=self.game((SILENCE,),board=(native.CLUSTER,));self.play(g,SILENCE,self.entity(g,native.CLUSTER,zone='board').id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,30)

    def test_glyph_buffs_original_target_and_neighbors_on_either_side(self):
        for p in(1,2):
            g=self.game((native.GLYPH,),enemy_board=(IDS[2][A],IDS[2][D],native.TROGG,POWER),player=p)
            ids=list(g.state.players[3-p].board);self.play(g,native.GLYPH,ids[1],player=p)
            self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in ids],[(2,14),(2,14),(3,5),(1,12)])

    def test_glyph_location_is_physical_neighbor_and_does_not_bridge_gap(self):
        g=self.game((native.GLYPH,),board=(IDS[2][A],native.FIST,IDS[2][D],native.TROGG))
        ids=list(g.state.players[1].board);self.play(g,native.GLYPH,ids[2])
        self.assertEqual(g.state.entities[ids[0]].health,12);self.assertEqual(g.state.entities[ids[1]].durability,2)
        self.assertEqual((g.state.entities[ids[2]].health,g.state.entities[ids[3]].health),(14,5))

    def test_canary_bounces_same_enemy_physical_entity_to_its_owner_hand(self):
        g=self.game((native.CANARY,),enemy_board=(IDS[2][A],));enemy=self.entity(g,IDS[2][A],2,'board')
        self.paid(g,native.CANARY,enemy.id)
        self.assertIn(enemy.id,g.state.players[2].hand);self.assertEqual(g.state.entities[enemy.id].zone,Zone.HAND)
        self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_canary_without_enemy_can_be_played_but_friendly_target_is_rejected(self):
        g=self.game((native.CANARY,),board=(IDS[2][A],));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,native.CANARY,self.entity(g,IDS[2][A],zone='board').id)
        self.assertEqual(g.snapshot(),before);self.play(g,native.CANARY)
        self.assertEqual(len(g.state.players[1].board),2)
        h=self.game((native.CANARY,),enemy_board=(IDS[2][A],));before=h.snapshot()
        with self.assertRaises(IllegalAction):self.play(h,native.CANARY)
        self.assertEqual(h.snapshot(),before)

    def test_magic_fist_is_paid_location_then_free_six_seven_activation_with_cooldown_and_two_uses(self):
        g=self.game((native.FIST,),enemy_board=(IDS[2][A],));target=self.entity(g,IDS[2][A],2,'board')
        loc=self.paid(g,native.FIST);mana=g.state.players[1].mana
        g.apply(UseLocation(1,loc,target.id));target=g.state.entities[target.id]
        self.assertEqual((target.attack,target.health),(6,7))
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(g.state.entities[loc].durability,1)
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,loc,target.id))
        self.portable(g)
        for _ in range(2):g.apply(EndTurn(1));g.apply(EndTurn(2))
        g.apply(UseLocation(1,loc,target.id));self.assertEqual(g.state.entities[loc].zone,Zone.GRAVEYARD)

    def test_three_cost_discoveries_keep_complete_original_offers_and_zero_price_on_real_play(self):
        for cid,cost in DISCOVER.items():
            g=self.game((cid,));self.paid(g,cid);choice=g.state.pending_choice
            self.assertIsNotNone(choice);offered={opt.card_id for opt in choice.options}
            self.assertEqual(offered,{IDS[cost][A],IDS[cost][D],IDS[cost][SP]})
            option=next(opt.id for opt in choice.options if opt.card_id==IDS[cost][SP])
            restored=self.portable(g);self.choose(g,option);self.choose(restored,option)
            self.assertEqual(g.snapshot(),restored.snapshot())
            gained=self.entity(g,IDS[cost][SP]);self.assertEqual(quote_cost(g.state,g.registry,gained).amount,0)
            armor=self.hero(g,1).armor;self.paid(g,IDS[cost][SP]);self.assertEqual(self.hero(g,1).armor,armor+3)

    def test_discovery_zero_price_survives_full_hand_burn_without_adding_excavation(self):
        g=self.game((native.FOOL,)+(NOOP,)*9,board=(FILL,));self.play(g,native.FOOL)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.choose(g,next(opt.id for opt in g.state.pending_choice.options if opt.card_id==IDS[2][SP]))
        burned=[e for e in g.state.entities.values()if e.card_id==IDS[2][SP]and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),1);self.assertFalse(g.state.excavation_history);self.portable(g)

    def test_living_stone_actual_death_summons_any_class_printed_two_cost_minion_at_death_slot(self):
        g=self.game((KILL,),board=(POWER,native.LIVING,native.TROGG));old=list(g.state.players[1].board)
        self.play(g,KILL,old[1]);now=g.state.players[1].board
        self.assertEqual((now[0],now[2]),(old[0],old[2]));self.assertNotIn(old[1],now)
        self.assertIn(g.state.entities[now[1]].card_id,(IDS[2][A],IDS[2][D]));self.portable(g)

    def test_living_stone_silence_does_not_run_random_death_summon(self):
        g=self.game((SILENCE,KILL),board=(native.LIVING,));target=self.entity(g,native.LIVING,zone='board')
        self.play(g,SILENCE,target.id);rng=g.snapshot()['rng_state'];self.play(g,KILL,target.id)
        self.assertFalse(g.state.players[1].board);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_ironshell_mole_real_untargetable_taunt_reborn_returns_once_at_one_health(self):
        g=self.game((KILL,ALL),board=(native.MOLE,));old=self.entity(g,native.MOLE,zone='board');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,KILL,old.id)
        self.assertEqual(g.snapshot(),before);self.play(g,ALL)
        new=self.entity(g,native.MOLE,zone='board');self.assertNotEqual(new.id,old.id);self.assertEqual(new.health,1)
        self.assertIn(Keyword.ELUSIVE,new.keywords);self.assertIn(Keyword.TAUNT,new.keywords);self.assertNotIn(Keyword.REBORN,new.keywords)

    def test_escape_trogg_rush_attacks_minion_immediately_but_cannot_attack_hero(self):
        g=self.game((native.TROGG,),enemy_board=(IDS[2][A],));source=self.play(g,native.TROGG);before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),before);g.apply(Attack(1,source,self.entity(g,IDS[2][A],2,'board').id))
        self.assertEqual(self.entity(g,IDS[2][A],2,'board').health,10)

    def test_unknown_eligible_discovery_and_death_summon_are_not_filtered_and_rollback(self):
        for cid,board,target in((native.FOOL,(),False),(KILL,(native.LIVING,),True)):
            g=self.game((cid,),board=board,mode='unknown');before=g.snapshot()
            with self.assertRaisesRegex(ValueError,'unsupported card definition'):
                self.play(g,cid,self.entity(g,native.LIVING,zone='board').id if target else None)
            self.assertEqual(g.snapshot(),before)

    def test_damage_reaction_failure_rolls_back_payment_damage_history_and_rng(self):
        g=self.game((native.COLLAPSE,),board=(FAIL,),enemy_board=(IDS[2][A],));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K608 deliberate'):self.play(g,native.COLLAPSE)
        self.assertEqual(g.snapshot(),before)

    def test_last_invalid_face_cannot_register_partial_cards_metadata_or_behaviors(self):
        data=deepcopy(native.load_batch());data['cards'][-1]['record']['collectible']=True
        r=batch.registration_prefix(build_registry,'hs_sim.cards.excavate_shared_treasures.register_excavate_shared_treasures',native.register_excavate_shared_treasures)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data):
            with self.assertRaises(TargetValidationError):native.register_excavate_shared_treasures(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
