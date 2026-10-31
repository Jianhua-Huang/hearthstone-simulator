"""Actual physical inventory, native conditions, equipment and residence edges."""
from dataclasses import replace
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_physical_inventory_weapons as native
from hs_sim.engine import Attack,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.excavate import Excavate
from hs_sim.engine.model import (BattlecryRepeatSpec,CardClass,CardDefinition,CardType,CostSpec,Keyword,LimitedTriggerSpec,TargetSpec,TribeChangeSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

PATCH,NADOX,FINLEY,KRUSH,THEOTAR,TONY,BENEDICTUS,BLING,MALKOROK,KURTRUS=native.ROOTS
TINY=native.EXISTING[0]
P='k729.'
A,UNDEAD,ALL,STRONG,EQUAL,SLEEP,SPAWNER,SMALL=(P+x for x in('a','undead','all','strong','equal','sleep','spawner','small'))
BUFF,CONTROL,RETURN,KILL,DIG,DIG1,DRAW,COST,DECK_BUFF,TRIBE,NOOP=(P+x for x in
    ('buff','control','return','kill','dig','dig1','draw','cost','deck_buff','tribe','noop'))
WEAPON,W2,OLD,WAIT_HAND,WAIT_DEATH,WAIT_COPY,WAIT_ATTACK,WAIT_SHUFFLE,FAIL,LOCATION,HERO,REPEAT=(P+x for x in
    ('weapon','weapon2','old','wait_hand','wait_death','wait_copy','wait_attack','wait_shuffle','fail','location','hero','repeat'))
CTX=GenerationContext(P+'fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',mode='small'):
    h=full(role);r=h.registry if mode=='host'else defaults()
    if mode!='host':
        for cid in native.EXISTING:
            if cid not in r.cards:r.register_card(h.registry.card(cid));r.register_pool_card(h.registry.pool_card(cid))
        native.register_past_physical_inventory_weapons(r)
    meta=metadata(collectible=False,tribes=())
    def spawn(c):return(SummonByCard(c.player_id,(SummonEntryMaterial(A),),SummonCause.capture(c)),)
    r.register_behavior(SPAWNER,spawn)
    for cid,atk,hp,tribes,kwargs in((A,2,12,(),{}),(UNDEAD,3,5,('undead',),{}),(ALL,4,5,('all',),{}),
            (STRONG,10,30,(),{}),(EQUAL,6,12,(),{}),(SLEEP,1,10,(),dict(dormant_turns=2)),
            (SPAWNER,4,3,('undead',),dict(deathrattle=SPAWNER)),(SMALL,1,2,(),{})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=atk,health=hp,
            metadata=metadata(collectible=False,tribes=tribes),**kwargs));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def stored(c):return CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    bodies={BUFF:lambda c:(Buff(c.target_id,4,0,c.source_id),),CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        RETURN:lambda c:(ReturnToHand(c.target_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        DIG:lambda c:(Excavate(c.player_id,c.source_id,count=2),),DIG1:lambda c:(Excavate(c.player_id,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),COST:lambda c:(ModifyStoredCost(stored(c),CostSpec(set_to=0),c.source_id),),
        DECK_BUFF:lambda c:(BuffStoredCard(stored(c),4,5,c.source_id),),
        TRIBE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),
        NOOP:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(BUFF,CONTROL,RETURN,KILL,TRIBE)else None
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=meta));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,atk,dur,cls in((WEAPON,2,3,CardClass.WARRIOR),(W2,4,2,CardClass.PALADIN)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,cost=1,attack=atk,durability=dur,metadata=metadata(cls,tribes=())))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K729 deliberate rollback')))
    def wait(c):
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        sources=[c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id in native.ROOTS]
        if sources:options+=(ChoiceOption('remove','Destroy original source',(Destroy(sources[0].id,c.source_id),)),)
        if sources:options+=(ChoiceOption('return','Return original source',(ReturnToHand(sources[0].id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(OLD,wait)
    r.register_card(CardDefinition(OLD,OLD,CardType.WEAPON,attack=1,durability=5,deathrattle=OLD,metadata=meta))
    events=((WAIT_HAND,'card_destroyed_in_hand'),(WAIT_DEATH,'minion_died'),(WAIT_COPY,'card_added_to_deck'),
        (WAIT_ATTACK,'attack_finished'),(WAIT_SHUFFLE,'card_shuffled'))
    for cid,event in events:
        r.register_behavior(cid,wait);r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,
            limited_triggers=(LimitedTriggerSpec(event,cid),),metadata=meta))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP,metadata=meta))
    hero=replace(r.card('HERO_08'),id=HERO,name=HERO,cost=1,hero_card=True,metadata=metadata(CardClass.MAGE,collectible=False,tribes=()))
    r.register_card(hero)
    for cid in(LOCATION,HERO):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,attack=0,health=10,
        battlecry_repeats=(BattlecryRepeatSpec(),),metadata=meta));r.register_pool_card(PoolCard.from_definition(r.card(REPEAT)))
    if mode!='host':
        members=(PoolMember(WEAPON),PoolMember(W2))
        if mode=='unknown':
            r.register_pool_card(PoolCard(P+'missing',CardType.WEAPON,1,metadata(CardClass.WARRIOR,tribes=())));members+=(PoolMember(P+'missing'),)
        r.register_pool(PoolDefinition('constructed.cards','1',CTX.target_id,CTX.mode,members))
    r.validate();return r,h.context if mode=='host'else CTX


class PhysicalInventoryWeaponTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,host=False,mode=None,watch=None,
            weapon=None,enemy_weapon=None,mana=40,seed=729):
        self.mode=mode or('host'if host else'small');r,ctx=fixture('writer',self.mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*8 if deck is None else deck,
            mana=mana,max_mana=40,mana_cap=40,armor=500,weapon_card_id=watch or weapon),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*8 if enemy_deck is None else enemy_deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=enemy_weapon)),seed=seed,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            count+=1;self.assertLess(count,70);c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)
    def faces(self,g,p=1,zone='deck'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]

    def test_complete_thirteen_source_rows_twenty_four_primary_faces_and_exact_existing_child(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),24);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),13)
        for cid in native.ROOTS+native.EXISTING:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_ten_actual_current_host_paid_entries_keep_full_weapon_pool(self):
        for cid in native.ROOTS:
            g=self.game((cid,A),enemy_hand=(SMALL,),host=True);sid=self.play(g,cid);self.finish(g)
            self.assertTrue(g.state.play_history[0].completed);self.assertEqual(g.state.play_history[0].source_id,sid)
        r=full().registry;p=r.pool('constructed.cards',full().context)
        weapons=[m.card_id for m in p.members if r.pool_card(m.card_id).kind==CardType.WEAPON and r.pool_card(m.card_id).metadata.collectible]
        self.assertEqual(len(weapons),42);self.assertTrue(all(c in r.cards for c in weapons))

    def test_Patchwerk_destroys_actual_one_in_each_opposing_zone_without_discarding(self):
        g=self.game((PATCH,UNDEAD),board=(A,),enemy=(UNDEAD,),enemy_hand=(UNDEAD,NOOP),enemy_deck=(UNDEAD,NOOP))
        hand=self.entity(g,UNDEAD,2).id;deck=self.entity(g,UNDEAD,2,'deck').id;board=self.unit(g,UNDEAD,2).id;self.play(g,PATCH)
        for i in(hand,deck,board):self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual([d.entity_id for d in g.state.death_history],[board]);self.assertEqual(len(g.state.discard_history),0)
        self.assertEqual(self.faces(g,2,'hand'),[NOOP]);self.assertEqual(self.faces(g,2),[NOOP]);self.assertEqual(self.unit(g,A).health,12);self.portable(g)

    def test_Patchwerk_empty_minion_inventories_consume_no_rng_or_fake_deaths(self):
        g=self.game((PATCH,),enemy=(SLEEP,),enemy_hand=(NOOP,),enemy_deck=(NOOP,));rng=g.snapshot()['rng_state'];self.play(g,PATCH)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.death_history);self.assertEqual(self.faces(g,2,'hand'),[NOOP])

    def test_Patchwerk_duplicate_physical_hands_have_one_actual_random_destruction(self):
        g=self.game((PATCH,),enemy_hand=(UNDEAD,)*5,enemy_deck=(NOOP,));original=set(g.state.players[2].hand);self.play(g,PATCH)
        lost=original-set(g.state.players[2].hand);self.assertEqual(len(lost),1);self.assertEqual(len(g.state.players[2].hand),4)
        self.assertFalse(g.state.death_history);self.portable(g)

    def test_Patchwerk_hand_destruction_wait_restores_original_later_zone_requests_and_rng(self):
        g=self.game((PATCH,),enemy=(A,),enemy_hand=(UNDEAD,),enemy_deck=(UNDEAD,),watch=WAIT_HAND);self.play(g,PATCH)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.players[2].deck),1);self.assertEqual(len(g.state.players[2].board),1)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertFalse(g.state.players[2].deck);self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_Nadox_uses_destroyed_current_Attack_and_buffs_all_actual_survivors(self):
        g=self.game((BUFF,NADOX),board=(UNDEAD,A),enemy=(A,));uid=self.unit(g,UNDEAD).id;self.play(g,BUFF,uid);self.play(g,NADOX,uid)
        self.assertEqual(g.state.entities[uid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.death_history[0].attack,7)
        self.assertEqual(self.unit(g,A).attack,9);self.assertEqual(self.unit(g,NADOX).attack,12);self.assertEqual(self.unit(g,A,2).attack,2);self.portable(g)

    def test_Nadox_deathrattle_summons_receive_reward_after_ordinary_death(self):
        g=self.game((NADOX,),board=(SPAWNER,));victim=self.unit(g,SPAWNER).id;self.play(g,NADOX,victim)
        self.assertEqual(self.unit(g,A).attack,6);self.assertEqual(self.unit(g,NADOX).attack,9);self.portable(g)

    def test_Nadox_current_tribe_and_all_tribe_are_legal_but_enemy_and_plain_minions_are_not(self):
        g=self.game((TRIBE,NADOX),board=(A,ALL),enemy=(UNDEAD,));aid=self.unit(g,A).id;self.play(g,TRIBE,aid)
        self.play(g,NADOX,aid);self.assertEqual(self.unit(g,ALL).attack,6)
        g=self.game((NADOX,),board=(A,),enemy=(UNDEAD,));old=g.snapshot()
        for target in(self.unit(g,A).id,self.unit(g,UNDEAD,2).id):
            with self.assertRaises(IllegalAction):self.play(g,NADOX,target)
            self.assertEqual(g.snapshot(),old)
        self.play(g,NADOX);self.assertEqual(self.unit(g,A).attack,2)
        g=self.game((NADOX,),board=(ALL,));self.play(g,NADOX,self.unit(g,ALL).id);self.assertEqual(self.unit(g,NADOX).attack,9)

    def test_Nadox_cannot_select_its_own_incoming_Battlecry_and_no_other_target_is_optional(self):
        g=self.game((NADOX,));sid=self.entity(g,NADOX).id;old=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,sid,sid))
        self.assertEqual(g.snapshot(),old);self.play(g,NADOX);self.assertFalse(g.state.death_history)

    def test_Nadox_death_wait_keeps_original_Attack_if_source_dies(self):
        g=self.game((NADOX,),board=(UNDEAD,A),watch=WAIT_DEATH);self.play(g,NADOX,self.unit(g,UNDEAD).id)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g);self.assertEqual(self.unit(g,A).attack,5);self.portable(g)

    def test_Finley_requires_two_actual_own_Excavations_and_transforms_to_exact_Tinyfin(self):
        g=self.game((DIG,FINLEY),enemy=(A,SPAWNER,SLEEP),host=True);own=list(g.state.players[1].board);original=list(g.state.players[2].board)
        self.play(g,DIG);self.assertEqual(len(g.state.excavation_history),2);self.play(g,FINLEY)
        self.assertEqual([g.state.entities[i].card_id for i in original],[TINY,TINY,SLEEP]);self.assertFalse(g.state.death_history)
        for i in original[:2]:self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(1,1))
        self.assertFalse(any(g.state.entities[i].card_id==A for i in g.state.players[2].board));self.portable(g)

    def test_Finley_one_or_opponent_Excavations_do_not_satisfy_actual_player(self):
        g=self.game((DIG1,FINLEY),enemy=(A,),enemy_hand=(DIG,),host=True);self.play(g,DIG1);g.apply(EndTurn(1));self.play(g,DIG,player=2)
        g.apply(EndTurn(2));self.play(g,FINLEY);self.assertEqual(self.unit(g,A,2).card_id,A);self.assertEqual(len(g.state.excavation_history),3)

    def test_Finley_does_not_lose_threshold_after_later_excavation_tiers(self):
        g=self.game((DIG,DIG1,FINLEY),board=(A,),enemy=(EQUAL,),host=True);self.play(g,DIG);self.play(g,DIG1);self.play(g,FINLEY)
        self.assertEqual(self.faces(g,2,'board'),[TINY]);self.assertEqual(self.unit(g,A).attack,2)

    def test_Plush_Krush_uses_strict_current_Attack_and_original_owner_decks(self):
        g=self.game((CONTROL,BUFF,KRUSH),board=(UNDEAD,),enemy=(A,EQUAL,STRONG));stolen=self.unit(g,A,2).id;own=self.unit(g,UNDEAD).id
        self.play(g,CONTROL,stolen);self.play(g,BUFF,own);self.play(g,KRUSH)
        self.assertEqual(g.state.entities[stolen].owner,2);self.assertIn(stolen,g.state.players[2].deck)
        self.assertIn(own,g.state.players[1].board);self.assertEqual(self.faces(g,2,'board'),[EQUAL,STRONG]);self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.deck_shuffle_history[-1].player_id,2);self.portable(g)

    def test_Plush_Krush_backward_reset_strips_buff_and_has_real_Charge(self):
        g=self.game((BUFF,KRUSH),board=(SMALL,),enemy=(A,),deck=());sid=self.unit(g,SMALL).id;self.play(g,BUFF,sid);self.play(g,KRUSH)
        self.assertIn(sid,g.state.players[1].deck);self.assertEqual(g.state.entities[sid].attack,1);self.assertEqual(len(g.state.deck_shuffle_history),2)
        g.apply(Attack(1,self.unit(g,KRUSH).id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,494);self.portable(g)

    def test_Plush_Krush_first_owner_shuffle_wait_does_not_cancel_second_after_source_death(self):
        g=self.game((KRUSH,),board=(A,),enemy=(UNDEAD,),watch=WAIT_SHUFFLE);self.play(g,KRUSH)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertFalse(g.state.players[2].board);self.assertEqual(len(g.state.deck_shuffle_history),2);self.portable(g)

    def test_Theotar_actual_native_entry_swaps_original_private_cards(self):
        g=self.game((THEOTAR,A),enemy_hand=(UNDEAD,));own=self.entity(g,A).id;other=self.entity(g,UNDEAD,2).id;self.play(g,THEOTAR)
        g=self.portable(g);self.finish(g);self.assertEqual(g.state.players[1].hand,[other]);self.assertEqual(g.state.players[2].hand,[own])
        self.assertEqual(len(g.state.card_discovery_history),2);self.portable(g)

    def test_Tony_replaces_whole_ordered_deck_with_new_original_material_and_no_fake_destruction(self):
        g=self.game((TONY,),deck=(SMALL,SPAWNER),enemy_deck=(UNDEAD,NOOP,WEAPON,LOCATION,HERO));old=tuple(g.state.players[1].deck);donor=tuple(g.state.players[2].deck)
        self.play(g,TONY);self.assertEqual(self.faces(g),[UNDEAD,NOOP,WEAPON,LOCATION,HERO]);self.assertEqual(tuple(g.state.players[2].deck),donor)
        for i in old:self.assertEqual(g.state.entities[i].zone,Zone.SETASIDE)
        self.assertTrue(set(g.state.players[1].deck).isdisjoint(donor));self.assertFalse(g.state.deck_shuffle_history);self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.discard_history);self.assertFalse(any(e.kind.startswith('card_destroyed_in_')for e in g.events));self.portable(g)

    def test_Tony_current_deck_buff_and_cost_copy_preserve_donor_and_new_ownership(self):
        g=self.game((TONY,),enemy_hand=(DECK_BUFF,COST),enemy_deck=(NOOP,UNDEAD));donor=self.entity(g,UNDEAD,2,'deck').id
        g.apply(EndTurn(1));self.play(g,DECK_BUFF,player=2);self.play(g,COST,player=2);g.apply(EndTurn(2));self.play(g,TONY)
        copied=self.entity(g,UNDEAD,1,'deck');self.assertEqual((copied.attack,copied.max_health,copied.cost,copied.owner),(7,10,0,1))
        self.assertEqual((g.state.entities[donor].attack,g.state.entities[donor].cost),(7,0));self.portable(g)

    def test_Tony_real_Finale_draws_new_top_once_and_nonfinale_does_not(self):
        g=self.game((TONY,),enemy_deck=(UNDEAD,A),mana=7);self.play(g,TONY);self.assertEqual(self.faces(g,1,'hand'),[UNDEAD]);self.assertEqual(self.faces(g),[A])
        self.assertTrue(g.state.play_history[0].finale);self.portable(g)
        g=self.game((TONY,),enemy_deck=(UNDEAD,A),mana=8);self.play(g,TONY);self.assertEqual(self.faces(g,1,'hand'),[]);self.assertFalse(g.state.play_history[0].finale)

    def test_Tony_empty_opposing_deck_replacement_and_Finale_uses_real_fatigue(self):
        g=self.game((TONY,),enemy_deck=(),mana=7);self.play(g,TONY);self.assertFalse(g.state.players[1].deck)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,499);self.assertFalse(g.state.deck_shuffle_history);self.portable(g)

    def test_Benedictus_keeps_original_own_deck_and_copies_all_five_playable_kinds_in_one_shuffle(self):
        g=self.game((BENEDICTUS,),deck=(SMALL,),enemy_deck=(UNDEAD,NOOP,WEAPON,LOCATION,HERO));old=g.state.players[1].deck[0];donor=tuple(g.state.players[2].deck)
        self.play(g,BENEDICTUS);self.assertIn(old,g.state.players[1].deck);self.assertCountEqual(self.faces(g),[SMALL,UNDEAD,NOOP,WEAPON,LOCATION,HERO])
        self.assertEqual(tuple(g.state.players[2].deck),donor);self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(g.state.deck_shuffle_history[0].declared_count,5);self.portable(g)

    def test_Benedictus_full_forty_card_donor_is_not_truncated_to_normal_starting_size(self):
        g=self.game((BENEDICTUS,),deck=(SMALL,)*3,enemy_deck=(UNDEAD,)*40);self.play(g,BENEDICTUS)
        self.assertEqual(len(g.state.players[1].deck),43);self.assertEqual(self.faces(g).count(UNDEAD),40);self.assertEqual(g.state.deck_shuffle_history[0].declared_count,40)

    def test_Benedictus_empty_donor_does_not_invent_shuffle_or_rng(self):
        g=self.game((BENEDICTUS,),enemy_deck=());rng=g.snapshot()['rng_state'];old=tuple(g.state.players[1].deck);self.play(g,BENEDICTUS)
        self.assertEqual(tuple(g.state.players[1].deck),old);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.deck_shuffle_history)

    def test_Benedictus_first_copy_wait_restores_complete_original_group_and_rollback(self):
        g=self.game((BENEDICTUS,),deck=(),enemy_deck=(UNDEAD,A,WEAPON),watch=WAIT_COPY);self.play(g,BENEDICTUS)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertCountEqual(self.faces(g),[UNDEAD,A,WEAPON]);self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g)

    def test_Blingtron_equips_both_without_bonus_or_class_restriction(self):
        g=self.game((BLING,),weapon=WEAPON,enemy_weapon=W2);old=(g.state.players[1].weapon_id,g.state.players[2].weapon_id);self.play(g,BLING)
        for pid in(1,2):
            e=g.state.entities[g.state.players[pid].weapon_id];printed=fixture()[0].card(e.card_id)
            self.assertIn(e.card_id,(WEAPON,W2));self.assertEqual((e.attack,e.durability),(printed.attack,printed.durability))
        for i in old:self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertFalse(any(e.kind=='weapon_modified'for e in g.events));self.portable(g)

    def test_Malkorok_only_equips_actor_leaving_original_enemy_slot_untouched(self):
        g=self.game((MALKOROK,),enemy_weapon=W2);old=g.state.players[2].weapon_id;self.play(g,MALKOROK)
        self.assertEqual(g.state.players[2].weapon_id,old);self.assertIn(g.state.entities[g.state.players[1].weapon_id].card_id,(WEAPON,W2));self.portable(g)

    def test_random_equipment_keeps_unknown_eligible_identity_and_rolls_back_instead_of_cropping(self):
        g=self.game((MALKOROK,),mode='unknown');old=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition: k729.missing'):self.play(g,MALKOROK)
        self.assertEqual(g.snapshot(),old)

    def test_Blingtron_old_weapon_deathrattle_wait_restores_actual_original_replacements(self):
        g=self.game((BLING,),weapon=OLD,enemy_weapon=W2);self.play(g,BLING);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.choose(g);self.finish(g)
        for pid in(1,2):self.assertIn(g.state.entities[g.state.players[pid].weapon_id].card_id,(WEAPON,W2))
        self.portable(g)

    def test_Kurtrus_real_Outcast_is_immune_before_both_original_edge_attacks(self):
        g=self.game((KURTRUS,),enemy=(A,STRONG,A));original=list(g.state.players[2].board);self.play(g,KURTRUS)
        self.assertEqual([g.state.entities[i].health for i in original],[9,30,9]);self.assertEqual(self.unit(g,KURTRUS).health,4)
        self.assertEqual(len(g.state.character_attack_history),2);self.assertIn(Keyword.IMMUNE,self.unit(g,KURTRUS).keywords);self.portable(g)

    def test_Kurtrus_single_surviving_enemy_is_attacked_twice_per_official_fix(self):
        g=self.game((KURTRUS,),enemy=(A,));self.play(g,KURTRUS);self.assertEqual(self.unit(g,A,2).health,6)
        self.assertEqual(len(g.state.character_attack_history),2);self.portable(g)

    def test_Kurtrus_middle_hand_without_Outcast_dies_to_first_retaliation_and_cannot_rebind(self):
        g=self.game((A,KURTRUS,UNDEAD),enemy=(STRONG,A));last=self.unit(g,A,2).id;source=self.play(g,KURTRUS)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[last].health,12)
        self.assertEqual(len(g.state.character_attack_history),1);self.assertFalse(g.state.play_history[0].outcast);self.portable(g)

    def test_Kurtrus_original_repeat_after_first_combat_death_does_not_invent_a_live_attacker(self):
        g=self.game((A,KURTRUS,UNDEAD),board=(REPEAT,),enemy=(STRONG,A));last=self.unit(g,A,2).id;source=self.play(g,KURTRUS)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[last].health,12)
        self.assertEqual(len(g.state.character_attack_history),1);self.assertTrue(g.state.play_history[0].completed);self.portable(g)

    def test_Kurtrus_Immune_expires_at_actual_turn_end(self):
        g=self.game((KURTRUS,),enemy=(A,),enemy_hand=(BUFF,));self.play(g,KURTRUS);g.apply(EndTurn(1))
        self.assertNotIn(Keyword.IMMUNE,self.unit(g,KURTRUS).keywords);self.portable(g)

    def test_Kurtrus_first_attack_wait_keeps_original_residence_and_return_cancels_second(self):
        g=self.game((KURTRUS,),enemy=(A,A),watch=WAIT_ATTACK);last=g.state.players[2].board[-1];self.play(g,KURTRUS)
        self.fault(g);g=self.portable(g);self.choose(g,'return');self.finish(g)
        self.assertEqual(g.state.entities[last].health,12);self.assertEqual(self.faces(g,1,'hand'),[KURTRUS]);self.portable(g)
