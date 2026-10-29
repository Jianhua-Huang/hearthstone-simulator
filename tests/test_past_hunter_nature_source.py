"""Original death discovery, distinct Wildseeds and actual decreasing CASTs."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
from random import Random
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from test_past_hunter_nature_leaves import fixture as leaf_fixture,CTX,A,B,WEAK,DORMANT,SHIELD,POWER,BEAST1,BEAST2,KILL
from hs_sim.cards import past_hunter_nature_source as native
from hs_sim.cards.simple_followup_p89_cards import WO,QUERIES
from hs_sim.engine import Attack,EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.decreasing_spell_damage import DecreasingRandomSpellDamage
from hs_sim.engine.effects import (ChoiceOption,Damage,GrantSpellDamage,InvokeBehavior,RandomDamage,RequestChoice,Silence,Summon)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,ChoicePurpose,Keyword,TriggerSpec
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest
from opening_fixtures import metadata

PET,SPIRITS,SHELL=native.ROOTS
FOX,BEAR,STAG=native.SEEDS
P='k669.'
BEAST3,BEAST4,WATCH,FAIL,AUTO,SPAWN,TOKEN,WEAPON=(P+x for x in('beast3','beast4','watch','fail','auto','spawn','token','weapon'))


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=leaf_fixture('k669-'+role);native.register_past_hunter_nature_cards(r)
    r.register_pool(PoolDefinition(native.WILDSEED_POOL,'k669-complete-three-seed-fixture',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in native.SEEDS),complete=True))
    for cid in(BEAST3,BEAST4):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=4,metadata=metadata(tribes=('beast',))))
    r.register_card(CardDefinition(TOKEN,TOKEN,CardType.MINION,attack=1,health=8,metadata=metadata(tribes=())))
    r.register_behavior(SPAWN,lambda c:(Summon(c.player_id,TOKEN),))
    r.register_card(CardDefinition(SPAWN,SPAWN,CardType.MINION,attack=1,health=1,deathrattle=SPAWN,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=1,durability=1,metadata=metadata()))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,SHELL,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=4,battlecry=AUTO,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K669 deliberate rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=SHELL:return()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        power=next((eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==POWER),None)
        if power is not None:options.append(ChoiceOption('drop','Silence original spell damage',(Silence(power),)))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class HunterNatureSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),watch=False,seed=669):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*18,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=('card.2',)*18,mana=10,max_mana=10)),seed=seed,generation_context=CTX),fixture())

    def ids(self,g,player=1):return[g.state.entities[eid].card_id for eid in g.state.players[player].board]

    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            self.choose(g);count+=1;self.assertLess(count,20)

    def amounts(self,g):
        rows=[dict(dict(e.data)['result'])for e in g._events if e.kind=='health_resolved']
        return[row['base_amount']for row in rows if row['source_card_id']==SHELL]

    def test_seven_complete_native_faces_and_all_original_members_have_real_definitions(self):
        d=native.load_batch();r=fixture();h=host()
        self.assertEqual(len(d['official_observations']),34);self.assertEqual(len(d['member_ids']),9)
        for row in d['cards']+d['dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        native.checked_native(h.registry,d)
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_pet_empty_or_only_nonbeast_death_has_no_choice_or_rng(self):
        for kill in(False,True):
            with self.subTest(kill=kill):
                g=self.game((PET,KILL)if kill else(PET,),board=(A,))
                if kill:self.play(g,KILL,self.entity(g,A,zone='board').id)
                rng=g.snapshot()['rng_state'];self.play(g,PET)
                self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
                self.assertEqual(g.state.players[1].mana,7)

    def test_pet_discovers_only_friendly_original_beast_and_ordinary_printed_resurrection(self):
        g=self.game((KILL,KILL,PET),board=(BEAST1,),enemy=(BEAST2,));original=self.entity(g,BEAST1,zone='board').id
        self.play(g,KILL,original);self.play(g,KILL,self.entity(g,BEAST2,2,'board').id);self.play(g,PET)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[BEAST1])
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CARD_DISCOVERY);self.portable(g)
        self.choose(g,g.state.pending_choice.options[0].id)
        revived=self.entity(g,BEAST1,zone='board');self.assertNotEqual(revived.id,original)
        self.assertEqual((revived.attack,revived.health),(2,4));self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_pet_duplicate_deaths_have_one_card_option_and_four_distinct_are_sampled_to_three(self):
        beasts=(BEAST1,BEAST1,BEAST2,BEAST3,BEAST4)
        g=self.game((KILL,)*5+(PET,),board=beasts)
        for cid in beasts:self.play(g,KILL,self.entity(g,cid,zone='board').id)
        self.play(g,PET);choice=g.state.pending_choice
        self.assertEqual(len(choice.options),3);self.assertEqual(len({o.card_id for o in choice.options}),3)
        self.assertTrue({o.card_id for o in choice.options}<={BEAST1,BEAST2,BEAST3,BEAST4});self.portable(g)
        self.choose(g,choice.options[0].id);self.assertEqual(len(g.state.card_discovery_history),1)

    def test_pet_full_board_still_records_discovery_without_evicting_or_allocating(self):
        g=self.game((KILL,A,PET),board=(BEAST1,)+(A,)*6)
        self.play(g,KILL,self.entity(g,BEAST1,zone='board').id);self.play(g,A)
        start=g.state.next_entity_id;self.play(g,PET);self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual(self.ids(g),[A]*7);self.assertEqual(g.state.next_entity_id,start)
        self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)

    def test_wild_spirits_selects_two_different_seeds_and_advances_their_actual_countdown(self):
        g=self.game((SPIRITS,));self.play(g,SPIRITS)
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(len(set(self.ids(g))),2)
        for eid in g.state.players[1].board:
            e=g.state.entities[eid];turns=native.SEEDS.index(e.card_id)
            self.assertEqual(None if e.dormancy is None else e.dormancy.remaining_turns,turns or None)
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_spirits_advances_existing_friendly_seeds_but_not_other_dormants_or_enemy(self):
        g=self.game((SPIRITS,),board=(FOX,BEAR,STAG,DORMANT),enemy=(STAG,))
        originals={g.state.entities[eid].card_id:eid for eid in g.state.players[1].board};self.play(g,SPIRITS)
        self.assertIsNone(g.state.entities[originals[FOX]].dormancy)
        self.assertEqual(g.state.entities[originals[BEAR]].dormancy.remaining_turns,1)
        self.assertEqual(g.state.entities[originals[STAG]].dormancy.remaining_turns,2)
        self.assertEqual(g.state.entities[originals[DORMANT]].dormancy.remaining_turns,2)
        self.assertEqual(self.entity(g,STAG,2,'board').dormancy.remaining_turns,3);self.portable(g)

    def test_full_spirits_board_keeps_original_occupants_but_still_advances_seeds(self):
        g=self.game((SPIRITS,),board=(BEAR,)+(A,)*6);original=self.entity(g,BEAR,zone='board').id;start=g.state.next_entity_id
        self.play(g,SPIRITS);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.next_entity_id,start);self.assertEqual(g.state.entities[original].dormancy.remaining_turns,1)

    def test_three_real_spirits_casts_awaken_original_stag_and_equip_real_four_two_weapon(self):
        g=self.game((SPIRITS,)*3,board=(STAG,));original=self.entity(g,STAG,zone='board').id
        for _ in range(3):self.play(g,SPIRITS)
        self.assertIsNone(g.state.entities[original].dormancy)
        weapon=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),(native.BOW,4,2));self.portable(g)

    def test_each_real_seed_can_be_played_and_natural_owner_starts_awaken_stag(self):
        g=self.game((FOX,BEAR,STAG))
        for cid in native.SEEDS:self.play(g,cid)
        for i in range(3):
            self.cycle(g)
            for cid in native.SEEDS[:i+1]:self.assertIsNone(self.entity(g,cid,zone='board').dormancy)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,native.BOW);self.portable(g)

    def test_wildbow_normal_hand_entry_equips_printed_weapon_and_pays_three(self):
        g=self.game((native.BOW,));self.play(g,native.BOW)
        self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual((g.state.entities[g.state.players[1].weapon_id].attack,g.state.entities[g.state.players[1].weapon_id].durability),(4,2))

    def test_shellshot_is_one_paid_cast_with_three_two_one_fresh_hits(self):
        g=self.game((SHELL,),enemy=(B,));self.play(g,SHELL)
        self.assertEqual(self.amounts(g),[3,2,1]);self.assertEqual(self.entity(g,B,2,'board').health,24)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual([x.card_id for x in g.state.cast_history],[SHELL]);self.portable(g)

    def test_shell_spell_damage_increases_both_damage_and_positive_number_repeat_count(self):
        g=self.game((SHELL,),board=(POWER,),enemy=(B,));self.play(g,SHELL)
        self.assertEqual(self.amounts(g),[5,4,3,2,1]);self.assertEqual(self.entity(g,B,2,'board').health,15)
        self.assertTrue(all(dict(dict(e.data)['result'])['spell_bonus']==0 for e in g._events if e.kind=='health_resolved'));self.portable(g)

    def test_shell_later_hits_see_deathrattle_spawn_and_do_not_hit_friendly_or_heroes(self):
        g=self.game((SHELL,),board=(A,),enemy=(SPAWN,));self.play(g,SHELL)
        self.assertEqual(self.ids(g,2),[TOKEN]);self.assertEqual(self.entity(g,TOKEN,2,'board').health,5)
        self.assertEqual(self.entity(g,A,zone='board').health,8)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[30,30]);self.portable(g)

    def test_shell_prevention_still_uses_next_positive_number_and_dormancy_is_excluded(self):
        g=self.game((SHELL,),enemy=(SHIELD,DORMANT));self.play(g,SHELL)
        self.assertEqual(self.entity(g,SHIELD,2,'board').health,1)
        self.assertEqual(self.entity(g,DORMANT,2,'board').health,8)
        self.assertEqual(self.amounts(g),[3,2,1])

    def test_shell_no_active_enemy_has_no_rng_consumption(self):
        g=self.game((SHELL,),enemy=(DORMANT,));rng=g.snapshot()['rng_state'];self.play(g,SHELL)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.amounts(g),[])

    def test_shell_waiting_next_step_restores_and_failed_rng_choice_is_atomic(self):
        g=self.game((SHELL,),enemy=(B,),watch=True);self.play(g,SHELL)
        self.assertEqual(self.amounts(g),[3]);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g)
        self.assertEqual(self.amounts(g),[3,2,1]);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_shell_local_current_bonus_policy_observes_provider_silenced_at_first_wait(self):
        g=self.game((SHELL,),board=(POWER,),enemy=(B,),watch=True);self.play(g,SHELL)
        self.assertEqual(self.amounts(g),[5]);self.choose(g,'drop');self.finish(g)
        self.assertEqual(self.amounts(g),[5,2,1]);self.assertEqual(self.entity(g,B,2,'board').health,22);self.portable(g)

    def test_actual_automatic_shell_from_minion_keeps_own_cast_and_no_spell_hand_payment(self):
        g=self.game((AUTO,),enemy=(B,));self.play(g,AUTO)
        self.assertEqual(self.amounts(g),[3,2,1]);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.cast_history[0].origin,'effect');self.portable(g)

    def test_decreasing_effect_has_strict_frozen_primitive_shape_and_frame_codec(self):
        for values in((True,1,1,3,0),(1,True,1,3,0),(1,1,True,3,0),(1,1,1,3,True),(1,1,1,0,0),(1,1,1,3,-1)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):DecreasingRandomSpellDamage(*values)
        g=self.game((SHELL,),enemy=(B,),watch=True);self.play(g,SHELL)
        effect=DecreasingRandomSpellDamage(1,g.state.cast_history[-1].id,g.state.cast_history[-1].source_id,step=1)
        codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(effect)),effect)

    def test_full_nine_and_three_pools_preserve_original_order_unit_weights_and_source_roles(self):
        h=host();d=native.load_batch();expected=native.local_pools(h.registry,h.context)
        self.assertEqual([p.id for p in expected],[native.HUNTER_NATURE_PAST_POOL,native.WILDSEED_POOL])
        for pool,source,query in((expected[0],WO,QUERIES[WO]),(expected[1],SPIRITS,native.SEED_QUERY)):
            actual=h.registry.pool(pool.id,h.context)
            self.assertEqual(actual,replace(pool,version=h.target_id+':'+pool.version))
            candidates=resolve_candidates(h.registry,h.context,pool.id,query,current_class=CardClass.HUNTER,source_card_id=source,exclude_source_by_rule=True)
            self.assertEqual([x.card_id for x in candidates],[x.card_id for x in pool.members]);self.assertTrue(all(x.weight==1 for x in candidates))
        self.assertEqual(d['member_ids'],list(native.MEMBERS))

    def test_source_rejects_missing_last_member_reordering_or_wrong_seed_weight(self):
        h=build_cn37_local_pool_format();original=h.registry.pool
        for poolindex in(0,1):
            for policy in('missing','reorder','weight'):
                with self.subTest(pool=poolindex,policy=policy):
                    pool=native.local_pools(h.registry,h.context)[poolindex]
                    real=h.registry.pool(pool.id,h.context);members=real.members
                    members=members[:-1]if policy=='missing'else tuple(reversed(members))if policy=='reorder'else(members[0],replace(members[1],weight=2),*members[2:])
                    with patch.object(h.registry,'pool',lambda pid,ctx:replace(real,members=members)if pid==real.id else original(pid,ctx)):
                        with self.assertRaises(TargetValidationError):native.register_scopes(h.registry,h.context)

    def test_real_host_wo_offers_full_nine_generated_shell_really_pays_and_hits(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        members=tuple(PoolMember(cid)for cid in native.MEMBERS)
        seed=next(seed for seed in range(1000)if SHELL in sample_candidates(Random(seed),members,3,replacement=False))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=('CORE_EX1_169',),board=(WO,),deck=deck,mana=7,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',),deck=deck,mana=10,max_mana=10)),seed=seed,generation_context=h.context),h.registry)
        self.play(g,'CORE_EX1_169');choice=g.state.pending_choice
        self.assertIsNotNone(choice);self.assertTrue({o.card_id for o in choice.options}<=set(native.MEMBERS))
        self.choose(g,next(o.id for o in choice.options if o.card_id==SHELL));before=g.state.players[1].mana;self.play(g,SHELL)
        self.assertEqual(self.ids(g,2),[]);self.assertEqual(g.state.players[1].mana,before-3)
        if g.state.pending_choice is not None:self.choose(g,g.state.pending_choice.options[0].id)
        self.portable(g)

    def test_real_host_wild_spirits_uses_source_bound_complete_three_pool(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(SPIRITS,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=669,generation_context=h.context),h.registry)
        self.play(g,SPIRITS);self.assertEqual(len(set(self.ids(g))),2);self.assertTrue(set(self.ids(g))<=set(native.SEEDS));self.portable(g)

    def test_real_host_pet_uses_actual_combat_death_discovery_and_original_wolf(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(PET,),board=('LOOT_077t',),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',),deck=deck,mana=10,max_mana=10)),seed=669,generation_context=h.context),h.registry)
        self.cycle(g);g.apply(Attack(1,g.state.players[1].board[0],g.state.players[2].board[0]));self.play(g,PET)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['LOOT_077t']);self.portable(g)
        self.choose(g,g.state.pending_choice.options[0].id);self.assertEqual(self.ids(g),['LOOT_077t']);self.portable(g)
