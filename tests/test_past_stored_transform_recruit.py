"""Real stored-consumer entries and their original materials/recovery boundaries."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from random import Random
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_fixed_rewards_turns import fixture as reward_fixture
from hs_sim.cards import past_stored_transform_recruit as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,Scenario
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.deck_cost_order import OrderDeckByCost
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,DamageKind,Keyword,
    LimitedTriggerSpec,Rarity,SummonStats,TargetSpec,TribeChangeSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.zones import CardReference,ModifyStoredCost

RAFAAM,LIAM,VOSS,POLKELT,PRESTOR,AVIANA,PIPSI,BASALEPH,ALURA,LILIAN=native.ROOTS
P='k735.'
A,N,L,D,SHIELD,RUSH,TAUNT,MULTI,U=(P+x for x in('a','one','legend','dragon','shield','rush','taunt','multi','undead'))
ZERO,KILL,BUFF,STORED,DISCOUNT,TRIBE,SILENCE,EXTRA,MAGE,WARRIOR,NEUTRAL,ENEMY,WAIT=(P+x for x in
    ('zero','kill','buff','stored','discount','tribe','silence','extra','mage','warrior','neutral','enemy','wait'))
WATCH_TRANS,WATCH_SUMMON,WATCH_SHUFFLE,FAIL=(P+x for x in('watch_transform','watch_summon','watch_shuffle','fault'))
CTX=GenerationContext(P+'complete-controlled-pool','experimental')


def fixture(role='writer',mode='small'):
    return cached_fixture(role,mode)


@lru_cache(None)
def cached_fixture(role,mode):
    r,host=reward_fixture(P+role+'.'+mode,'host'if mode=='host'else'small')
    if mode!='host':native.register_past_stored_transform_recruit(r)
    plain=metadata(collectible=False,tribes=())
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,atk,hp,keywords,tribes in((A,2,2,3,(),()),(N,1,1,4,(),()),
            (L,5,7,9,(),()),(D,8,8,8,(Keyword.TAUNT,),('dragon',)),
            (SHIELD,3,2,2,(Keyword.DIVINE_SHIELD,),()),(RUSH,4,3,3,(Keyword.RUSH,),()),
            (TAUNT,6,4,4,(Keyword.TAUNT,),()),
            (MULTI,2,2,2,(Keyword.DIVINE_SHIELD,Keyword.RUSH,Keyword.TAUNT),()),(U,2,1,3,(),('undead',))):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,keywords=keywords,
            battlecry=P+'cry'if cid in(L,SHIELD,RUSH,TAUNT)else None,
            metadata=metadata(rarity=Rarity.LEGENDARY if cid in(L,D)else Rarity.COMMON,tribes=tribes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def wait(c):return(RequestChoice(c.player_id,(
        ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
        ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))) ,c.source_id),)
    bodies={ZERO:lambda c:(),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        STORED:lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,3,c.source_id),),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=1),c.source_id),),
        TRIBE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),),EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),
        MAGE:lambda c:(Buff(c.target_id,2,3,c.source_id),),WARRIOR:lambda c:(GainArmor(c.player_id,3),),
        NEUTRAL:lambda c:(),ENEMY:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),WAIT:wait}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=(TargetSpec(zones=(Zone.HAND,Zone.DECK,Zone.BOARD),kinds=(CardType.MINION,))if cid in(STORED,DISCOUNT)else
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')if cid==ENEMY else
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,BUFF,TRIBE,SILENCE,MAGE)else None)
        card=CardDefinition(cid,cid,CardType.SPELL,cost=15 if cid in(MAGE,WAIT,ENEMY)else 0,on_play=cid,targeting=target,
            metadata=metadata(CardClass.MAGE if cid==MAGE else CardClass.WARRIOR if cid==WARRIOR else CardClass.NEUTRAL,
                tribes=())if cid in(MAGE,WARRIOR,NEUTRAL)else plain)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K735 deliberate rollback')))
    for cid,event in((WATCH_TRANS,'stored_card_transformed'),(WATCH_SUMMON,'minion_summoned'),(WATCH_SHUFFLE,'card_added_to_deck')):
        r.register_behavior(cid,wait);r.register_trigger_condition(cid,lambda c:c.event.action>0)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    if mode!='host':
        ids=(A,N,L,D,SHIELD,RUSH,TAUNT,MULTI,U,MAGE,WARRIOR,NEUTRAL)
        if mode=='empty':ids=()
        if mode=='unknown':
            unknown=CardDefinition(P+'unknown',P+'unknown',CardType.MINION,cost=2,attack=2,health=2,
                metadata=metadata(rarity=Rarity.LEGENDARY,tribes=('dragon',)))
            r.register_pool_card(PoolCard.from_definition(unknown));ids=(*ids,unknown.id)
        r.register_pool(PoolDefinition(native.POOL,P+'complete-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in ids)))
    r.validate();return r,host if mode=='host'else CTX


class StoredTransformRecruitTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,weapon=None,mode='small',seed=735,active=1):
        self.mode=mode;r,ctx=fixture('writer',mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,board=board,
            deck=(A,)*4 if deck is None else deck,mana=50,max_mana=50,mana_cap=50,armor=500,weapon_card_id=weapon),
            PlayerSetup('HERO_01',hero_power_card_id='HERO_01bp',hand=enemy_hand,board=enemy,
            deck=(A,)*4 if enemy_deck is None else enemy_deck,mana=50,max_mana=50,mana_cap=50,armor=500)),
            active_player=active,seed=seed,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def drain(self,g):
        while g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
    def fault(self,g):
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)

    def test_complete_fifteen_original_rows_twenty_four_faces_and_eleven_definitions(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),24)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','evidence_only')),15)
        self.assertEqual(len(d['original_candidate_ids']),732)
        for cid in native.ROOTS+native.DEPENDENCIES:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))
        token=fixture()[0].card(native.TOKEN);self.assertEqual((token.cost,token.attack,token.health),(4,4,2));self.assertIsNone(token.battlecry)

    def test_all_ten_current_host_roots_and_exact_child_actual_paid_entries(self):
        for cid in native.ROOTS+native.DEPENDENCIES:
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(A,),enemy=(A,),mode='host');old=g.state.players[1].mana
                self.play(g,cid);self.drain(g);self.assertEqual(g.state.players[1].mana,old-g.registry.card(cid).cost)
                self.assertTrue(any(row.card_id==cid for row in g.state.play_history))

    def test_Rafaam_transforms_original_remaining_hand_and_deck_all_types(self):
        g=self.game((RAFAAM,A,ZERO),deck=(A,ZERO,N),enemy_hand=(A,));original=tuple(g.state.players[1].hand[1:]+g.state.players[1].deck)
        self.play(g,RAFAAM)
        self.assertEqual(set(original),set(g.state.players[1].hand+g.state.players[1].deck))
        self.assertTrue(set(self.faces(g)+self.faces(g,zone='deck'))<={L,D});self.assertEqual(self.faces(g,2),[A])
        self.assertIn(Keyword.TAUNT,self.unit(g,RAFAAM).keywords);self.portable(g)

    def test_Rafaam_empty_inventory_does_not_draw_rng_or_require_unused_pool(self):
        g=self.game((RAFAAM,),deck=(),mode='empty');before=g.snapshot()['rng_state'];self.play(g,RAFAAM)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.faces(g),[])

    def test_Liam_selects_original_local_one_cost_deck_cards_and_preserves_others(self):
        g=self.game((LIAM,DISCOUNT,N),deck=(N,A,ZERO));a=self.entity(g,A,zone='deck');n=self.entity(g,N,zone='deck');z=self.entity(g,ZERO,zone='deck')
        self.play(g,DISCOUNT,a.id);self.play(g,LIAM)
        self.assertTrue({g.state.entities[a.id].card_id,g.state.entities[n.id].card_id}<={L,D})
        self.assertEqual(g.state.entities[z.id].card_id,ZERO);self.assertEqual(self.faces(g),[N]);self.portable(g)

    def test_Voss_uses_complete_actual_opponent_class_for_spells_only(self):
        g=self.game((VOSS,MAGE,ZERO,A),deck=(MAGE,),enemy_hand=(MAGE,));refs=g.state.players[1].hand[1:]
        self.play(g,VOSS);self.assertEqual(self.faces(g),[WARRIOR,WARRIOR,A]);self.assertEqual(self.faces(g,zone='deck'),[MAGE])
        self.assertEqual(tuple(g.state.players[1].hand),tuple(refs));self.assertEqual(self.faces(g,2),[MAGE]);self.portable(g)

    def test_Polkelt_uses_local_cost_full_permutation_and_only_randomises_ties(self):
        g=self.game((POLKELT,DISCOUNT),deck=(A,L,N,RUSH));l=self.entity(g,L,zone='deck');self.play(g,DISCOUNT,l.id)
        original=list(g.state.players[1].deck);rng=Random();rng.setstate(g._rng.getstate());tied=[l.id,self.entity(g,N,zone='deck').id];rng.shuffle(tied)
        self.play(g,POLKELT)
        self.assertEqual(g.state.players[1].deck,[self.entity(g,RUSH,zone='deck').id,self.entity(g,A,zone='deck').id,*tied])
        self.assertEqual(set(g.state.players[1].deck),set(original));self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(g.state.deck_shuffle_history,[]);self.portable(g)

    def test_Polkelt_distinct_costs_and_empty_deck_do_not_consume_rng(self):
        for deck in((),(N,L,A)):
            with self.subTest(deck=deck):
                g=self.game((POLKELT,),deck=deck);old=g.snapshot()['rng_state'];self.play(g,POLKELT)
                self.assertEqual(g.snapshot()['rng_state'],old);self.assertEqual(self.faces(g,zone='deck'),sorted(deck,key=lambda x:g.registry.card(x).cost,reverse=True))

    def test_Prestor_keeps_original_physical_numbers_cost_and_resets_abilities(self):
        g=self.game((PRESTOR,STORED,DISCOUNT),deck=(A,ZERO,N));a=self.entity(g,A,zone='deck');n=self.entity(g,N,zone='deck');z=self.entity(g,ZERO,zone='deck')
        self.play(g,STORED,a.id);self.play(g,DISCOUNT,a.id);self.play(g,PRESTOR)
        transformed=g.state.entities[a.id];self.assertEqual((transformed.card_id,transformed.attack,transformed.max_health),(D,4,6))
        from hs_sim.engine.costs import local_cost
        self.assertEqual(local_cost(transformed)[0],1);self.assertIn(Keyword.TAUNT,transformed.keywords)
        self.assertEqual((g.state.entities[n.id].attack,g.state.entities[n.id].max_health),(1,4));self.assertEqual(g.state.entities[z.id].card_id,ZERO)
        self.assertEqual(g.state.players[1].deck,[a.id,z.id,n.id]);self.portable(g)

    def test_Prestor_wait_restores_original_remaining_numbers_and_random_draws(self):
        g=self.game((PRESTOR,),deck=(A,N),weapon=WATCH_TRANS);self.play(g,PRESTOR);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_retained_deck_and_unbounded_cast_declarations_reject_unrelated_shapes(self):
        ref=CardReference(entity_id=10,player_id=1,zone=Zone.DECK,card_id='CS2_168',zone_epoch=1)
        with self.assertRaises(ValueError):TransformStoredFromPool(ref,native.POOL,native.LEGENDARY,9,retained_stats=SummonStats(attack=1,health=2),retained_cost=1)
        with self.assertRaises(ValueError):CastRandomDeckSpell(1,None,9)
        with self.assertRaises(ValueError):OrderDeckByCost(True,9)

    def test_Aviana_generates_ten_one_cost_legendaries_one_semantic_operation(self):
        g=self.game((AVIANA,),deck=(A,N));old=set(g.state.players[1].deck);self.play(g,AVIANA)
        created=[g.state.entities[i]for i in g.state.players[1].deck if i not in old]
        self.assertEqual(len(created),10);self.assertTrue({e.card_id for e in created}<={L,D})
        from hs_sim.engine.costs import local_cost
        self.assertTrue(all(local_cost(e)[0]==1 for e in created));self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,10);self.assertEqual(g.state.deck_shuffle_history[0].actor_id,1)
        self.assertTrue(any(e.kind=='deck_shuffled'for e in g.events));self.portable(g)

    def test_Aviana_randomises_previously_ordered_original_deck_too(self):
        outcomes=set()
        for seed in range(4):
            g=self.game((POLKELT,AVIANA),deck=(N,A,L,D),seed=seed);self.play(g,POLKELT);original=tuple(g.state.players[1].deck);self.play(g,AVIANA)
            outcomes.add(tuple(i for i in g.state.players[1].deck if i in original))
        self.assertGreater(len(outcomes),1)

    def test_Aviana_generated_group_wait_restore_and_failed_choice_are_atomic(self):
        g=self.game((AVIANA,),deck=(A,N),weapon=WATCH_SHUFFLE);self.play(g,AVIANA)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);h=self.portable(g);self.drain(g);self.drain(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(g.state.players[1].deck),12)

    def test_complete_unknown_pool_member_rolls_back_without_cropping_or_rng(self):
        for cid in(RAFAAM,PRESTOR,AVIANA):
            with self.subTest(cid=cid):
                g=self.game((cid,A),deck=(A,),mode='unknown');saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_Pipsi_three_actual_keyword_recruits_keep_original_ids_and_no_Battlecry(self):
        g=self.game((KILL,),board=(PIPSI,),deck=(SHIELD,RUSH,TAUNT));ids=tuple(g.state.players[1].deck);armor=g.state.entities[g.state.players[1].hero_id].armor
        self.play(g,KILL,self.unit(g,PIPSI).id)
        self.assertEqual(g.state.players[1].board,list(ids));self.assertEqual(self.faces(g,zone='deck'),[])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,armor);self.portable(g)

    def test_Pipsi_one_multi_keyword_physical_card_cannot_fill_three_slots(self):
        g=self.game((KILL,),board=(PIPSI,),deck=(MULTI,));original=g.state.players[1].deck[0];self.play(g,KILL,self.unit(g,PIPSI).id)
        self.assertEqual(g.state.players[1].board,[original]);self.assertEqual(g.state.players[1].deck,[])

    def test_Pipsi_empty_and_full_board_share_original_capacity_and_no_fallback(self):
        g=self.game((KILL,),board=(PIPSI,)+(A,)*6,deck=(SHIELD,RUSH,TAUNT));self.play(g,KILL,self.unit(g,PIPSI).id)
        self.assertEqual(self.faces(g,zone='deck'),[RUSH,TAUNT]);self.assertEqual(len(g.state.players[1].board),7)
        g=self.game((KILL,),board=(PIPSI,),deck=(A,));old=g.snapshot()['rng_state'];self.play(g,KILL,self.unit(g,PIPSI).id)
        self.assertEqual(g.snapshot()['rng_state'],old);self.assertEqual(self.faces(g,zone='deck'),[A])

    def test_Pipsi_recruit_wait_restores_original_remaining_queries(self):
        g=self.game((KILL,),board=(PIPSI,),deck=(SHIELD,RUSH,TAUNT),weapon=WATCH_SUMMON);self.play(g,KILL,self.unit(g,PIPSI).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Basaleph_after_last_actual_own_turn_excludes_older_and_enemy_deaths(self):
        g=self.game((KILL,BASALEPH),board=(U,U),enemy_hand=(KILL,),deck=(A,)*4)
        self.play(g,KILL,self.unit(g,U).id);g.apply(EndTurn(1));self.play(g,KILL,self.unit(g,U).id,player=2);g.apply(EndTurn(2));self.play(g,BASALEPH)
        self.assertEqual(self.faces(g,zone='board').count(U),1);self.portable(g)

    def test_Basaleph_first_owner_interval_and_actual_current_Undead_death(self):
        g=self.game((TRIBE,KILL,BASALEPH),board=(A,));self.play(g,TRIBE,self.unit(g,A).id);self.play(g,KILL,self.unit(g,A).id);self.play(g,BASALEPH)
        self.assertEqual(self.faces(g,zone='board').count(A),1);self.assertEqual((self.unit(g,A).attack,self.unit(g,A).max_health),(2,3));self.portable(g)

    def test_Basaleph_consecutive_actual_own_turns_do_not_use_turn_parity(self):
        g=self.game((KILL,EXTRA,BASALEPH),board=(U,));self.play(g,KILL,self.unit(g,U).id);self.play(g,EXTRA);g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1);self.play(g,BASALEPH);self.assertNotIn(U,self.faces(g,zone='board'));self.portable(g)

    def test_Basaleph_resurrection_wait_keeps_actual_death_occurrences(self):
        g=self.game((KILL,BASALEPH),board=(U,),weapon=WATCH_SUMMON);self.play(g,KILL,self.unit(g,U).id);self.play(g,BASALEPH)
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Alura_unbounded_actual_deck_spell_prefers_original_self_and_pays_no_spell_mana(self):
        g=self.game((ZERO,ZERO),board=(ALURA,A),deck=(MAGE,));original=g.state.players[1].deck[0];self.play(g,ZERO)
        self.assertEqual((self.unit(g,ALURA).attack,self.unit(g,ALURA).max_health),(5,9));self.assertEqual(g.state.players[1].mana,50)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertEqual(self.faces(g,zone='deck'),[])
        self.play(g,ZERO);self.assertEqual(len(g.state.cast_history),3);self.portable(g)

    def test_Alura_illegal_self_target_falls_back_to_original_legal_enemy(self):
        g=self.game((ZERO,),board=(ALURA,),enemy=(A,),deck=(ENEMY,));self.play(g,ZERO)
        self.assertEqual(self.unit(g,A,2).health,2);self.assertEqual(self.unit(g,ALURA).health,6);self.portable(g)

    def test_Alura_empty_spell_domain_consumes_once_without_rng_or_fatigue(self):
        g=self.game((ZERO,),board=(ALURA,),deck=(A,));before=g.snapshot()['rng_state'];self.play(g,ZERO)
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.faces(g,zone='deck'),[A])
        self.assertTrue(any(a.kind=='limited_trigger'and a.consumed for a in self.unit(g,ALURA).abilities))

    def test_Alura_original_spell_wait_restores_then_continues_real_deck_CAST(self):
        g=self.game((WAIT,),board=(ALURA,),deck=(MAGE,));self.play(g,WAIT);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.unit(g,ALURA).attack,self.unit(g,ALURA).max_health),(5,9));self.portable(g)

    def test_Lilian_real_Deathrattle_delivers_exact_token_and_actually_attacks_hero(self):
        g=self.game((KILL,),board=(LILIAN,));armor=g.state.entities[g.state.players[2].hero_id].armor;self.play(g,KILL,self.unit(g,LILIAN).id)
        self.assertEqual((self.unit(g,native.TOKEN).attack,self.unit(g,native.TOKEN).health),(4,2))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,armor-4);self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_Lilian_silence_prevents_token_or_attack(self):
        g=self.game((SILENCE,KILL),board=(LILIAN,));self.play(g,SILENCE,self.unit(g,LILIAN).id);self.play(g,KILL,self.unit(g,LILIAN).id)
        self.assertEqual(g.state.character_attack_history,[]);self.assertNotIn(native.TOKEN,self.faces(g,zone='board'))

    def test_Lilian_summon_wait_preserves_original_delivered_attacker(self):
        g=self.game((KILL,),board=(LILIAN,),weapon=WATCH_SUMMON);self.play(g,KILL,self.unit(g,LILIAN).id);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(g.state.character_attack_history),1)

    def test_both_player_DTOs_hide_original_transform_numbers_inventory_and_rng(self):
        g=self.game((PRESTOR,),deck=(A,N),weapon=WATCH_TRANS);self.play(g,PRESTOR)
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe())
            for key in('retained_stats','retained_cost','StoredPoolTransformDraw','rng_before','rng_after','resolution_frame'):
                self.assertNotIn('"'+key+'"',view)
        self.drain(g)

