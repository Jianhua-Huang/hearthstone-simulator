"""Five real original event consumers and guarded dynamic doubling."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_legendary_event_draws as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,CopyMinion,Damage,DamageBatch,Draw,
    GainArmor,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,CastWhenDrawnSpec,DamageKind,Keyword,SpellRepeatSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.sacrifice import DoubleCapturedMinionStats,MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

ACID,CHROMA,LUNA,GENZO,GAH=native.ROOTS
P='k688.';A=P+'plain';SHIELD=P+'shield';IMMUNE=P+'immune';DOUBLE=P+'double';COUNTER=P+'counter'
NOOP=P+'noop';HURT=P+'hurt';ZERO=P+'zero';TWO=P+'two';AREA=P+'area';DRAW=P+'draw';DRAW2=P+'draw2'
ADD=P+'add';FILLDRAW=P+'filldraw';HUSH=P+'hush';OUT=P+'out';COPY=P+'copy';BOOST=P+'boost';DECKBUFF=P+'deckbuff'
AUTO=P+'auto';CASTER=P+'caster';DRAW_WATCH=P+'draw_watch';DAMAGE_WATCH=P+'damage_watch'
WATCH=P+'watch';FAIL=P+'fail';REENTER=P+'reenter';QUEUE=P+'queue'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_legendary_event_draws(r)
    for cid,keywords in((A,()),(SHIELD,(Keyword.DIVINE_SHIELD,)),(IMMUNE,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=40,keywords=keywords,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),),metadata=metadata(collectible=False)))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=40,
        triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    def deckbuff(c):
        e=c.state.entities[c.state.players[c.player_id].deck[0]]
        return(BuffStoredCard(CardReference.capture(e),2,3,c.source_id),)
    def area(c):
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)for p in(1,2)
            for i in c.state.players[p].board if c.state.entities[i].active)),)
    def queue(c):
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('grow','Grow first',(
            Buff(c.target_id,2,0,c.source_id),)),ChoiceOption('fault','Fail after random damage',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),
            DoubleCapturedMinionStats(MinionReference.capture(c.state.entities[c.target_id]),attack=True,source_id=c.source_id))
    scripts={NOOP:lambda c:(),HURT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),
        TWO:lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)*2),),AREA:area,
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),DRAW2:lambda c:(Draw(c.player_id,2,c.source_id),),
        ADD:lambda c:(AddToHand(c.player_id,A,c.source_id),),FILLDRAW:lambda c:(AddToHand(c.player_id,A,c.source_id),Draw(c.player_id,1,c.source_id)),
        HUSH:lambda c:(Silence(c.target_id),),
        OUT:lambda c:(ReturnToHand(c.target_id),),BOOST:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),DECKBUFF:deckbuff,QUEUE:queue}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,
            targeting=board if cid in(HURT,ZERO,TWO,HUSH,OUT,BOOST,COPY,QUEUE)else None,metadata=metadata(collectible=False)))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,NOOP,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=40,battlecry=AUTO,metadata=metadata(collectible=False)))
    r.register_behavior(CASTER,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(CASTER,CASTER,CardType.SPELL,cost=3,on_play=CASTER,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False),metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K688 deliberate notification rollback')))
    r.register_behavior(REENTER,lambda c:(SummonFromZone(c.player_id,zone=Zone.HAND,
        query=PoolQuery(card_ids=(GAH,)),source_id=c.source_id,cause=SummonCause.capture(c)),))
    def watch(c):
        if c.event.kind=='card_drawn':
            if c.event.player_id!=c.player_id:return()
            target=c.state.entities[c.event.target_id]
            modify=(MoveCard(CardReference.capture(target),c.player_id,Zone.DECK,position='bottom',source_id=c.source_id),)
        else:
            if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=GAH:return()
            modify=(ReturnToHand(c.event.target_id),InvokeBehavior(REENTER,c.source_id,c.player_id,c.event.target_id))
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('move','Move original',modify),
            ChoiceOption('fault','Fail',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((DRAW_WATCH,'card_drawn'),(DAMAGE_WATCH,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,
            triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastLegendaryEventDrawTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*20,enemy_deck=(A,)*20,player=1):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=deck if p==player else enemy_deck,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),
            active_player=player,seed=688),fixture('writer'))
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def attack(self,g,cid=GENZO,p=1):g.apply(Attack(p,self.unit(g,cid,p).id,g.state.players[3-p].hero_id))

    def test_complete_five_original_faces_and_full_732_membership(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),14)
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])

    def test_all_five_actual_normal_paid_entries_keep_printed_stats(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);card=fixture().card(cid)
                self.assertEqual(g.state.players[1].mana,20-card.cost)
                self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(card.attack,card.health))
                self.assertEqual(self.hand(g),[])

    def test_acidmaw_destroys_only_enemy_damaged_minion(self):
        g=self.game((HURT,HURT),board=(ACID,A),enemy=(A,));friendly=self.unit(g,A).id;enemy=self.unit(g,A,2).id
        self.play(g,HURT,friendly);self.assertEqual(g.state.entities[friendly].health,39)
        self.play(g,HURT,enemy);self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD);self.portable(g)

    def test_acidmaw_zero_shield_and_immune_damage_do_not_destroy(self):
        g=self.game((ZERO,HURT,AREA),board=(ACID,),enemy=(A,SHIELD,IMMUNE))
        for spell,cid in((ZERO,A),(HURT,SHIELD)):
            target=self.unit(g,cid,2).id;self.play(g,spell,target);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)
        self.assertEqual(len(g.state.players[2].board),3)
        target=self.unit(g,IMMUNE,2).id;self.play(g,AREA)
        self.assertEqual((g.state.entities[target].zone,g.state.entities[target].health),(Zone.BOARD,40))

    def test_acidmaw_silence_retires_its_damage_listener(self):
        g=self.game((HUSH,HURT),board=(ACID,),enemy=(A,));self.play(g,HUSH,self.unit(g,ACID).id)
        target=self.unit(g,A,2).id;self.play(g,HURT,target);self.assertEqual(g.state.entities[target].health,39)

    def test_acidmaw_area_keeps_friendly_and_captures_both_enemy_recipients(self):
        g=self.game((AREA,),board=(ACID,A),enemy=(A,A));targets=tuple(g.state.players[2].board);self.play(g,AREA)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in targets))
        self.assertEqual(self.unit(g,A).health,39);self.assertEqual(self.unit(g,ACID).health,1);self.portable(g)

    def test_gahzrilla_two_same_batch_packets_double_current_attack_twice(self):
        g=self.game((TWO,),board=(GAH,));source=self.unit(g,GAH).id;self.play(g,TWO,source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(24,7));self.portable(g)

    def test_gahzrilla_uses_buffed_current_attack_and_original_health(self):
        g=self.game((BOOST,TWO),board=(GAH,));source=self.unit(g,GAH).id;self.play(g,BOOST,source);self.play(g,TWO,source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(32,10))

    def test_gahzrilla_zero_and_other_minion_damage_do_not_double(self):
        g=self.game((ZERO,HURT),board=(GAH,A));self.play(g,ZERO,self.unit(g,GAH).id);self.play(g,HURT,self.unit(g,A).id)
        self.assertEqual(self.unit(g,GAH).attack,6)

    def test_gahzrilla_current_copy_and_silence_use_original_stat_lifecycle(self):
        g=self.game((HURT,COPY,HUSH,HURT),board=(GAH,));source=self.unit(g,GAH).id;self.play(g,HURT,source)
        self.play(g,COPY,source);copies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==GAH]
        self.assertEqual([e.attack for e in copies],[12,12]);self.play(g,HUSH,source);self.play(g,HURT,source)
        self.assertEqual(g.state.entities[source].attack,6);self.assertEqual(g.state.entities[copies[1].id].attack,12);self.portable(g)

    def test_gahzrilla_pending_damage_does_not_buff_same_id_reentry(self):
        g=self.game((HURT,),board=(DAMAGE_WATCH,GAH));source=self.unit(g,GAH).id;epoch=g.state.entities[source].zone_epoch
        self.play(g,HURT,source);g=self.portable(g);self.choose(g,'move')
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertGreater(g.state.entities[source].zone_epoch,epoch)
        self.assertEqual(g.state.entities[source].attack,6);self.portable(g)

    def test_chromaggus_draw_copies_once_without_creating_another_draw(self):
        g=self.game((DRAW,),board=(CHROMA,));self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A,A]);self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(len(set(g.state.players[1].hand)),2);self.portable(g)

    def test_chromaggus_current_deck_stats_survive_in_the_independent_copy(self):
        g=self.game((DECKBUFF,DRAW),board=(CHROMA,));self.play(g,DECKBUFF);self.play(g,DRAW)
        bodies=[g.state.entities[i]for i in g.state.players[1].hand]
        self.assertEqual([(e.attack,e.health)for e in bodies],[(3,43),(3,43)]);self.portable(g)

    def test_chromaggus_two_draws_make_four_cards_and_two_original_records(self):
        g=self.game((DRAW2,),board=(CHROMA,));self.play(g,DRAW2)
        self.assertEqual(self.hand(g),[A]*4);self.assertEqual(len(g.state.draw_history),2)

    def test_chromaggus_plain_add_and_opponent_draw_are_not_own_draws(self):
        g=self.game((ADD,),board=(CHROMA,));self.play(g,ADD);self.assertEqual(self.hand(g),[A])
        self.end(g);self.assertEqual(self.hand(g),[A]);self.assertEqual(self.hand(g,2),[A]);self.assertEqual(len(g.state.draw_history),1)

    def test_chromaggus_fatigue_and_overdraw_do_not_create_extra_copies(self):
        g=self.game((DRAW,),board=(CHROMA,),deck=());self.play(g,DRAW)
        self.assertEqual(self.hand(g),[]);self.assertEqual(self.hero(g).health,29)
        full=self.game((DRAW,)+(A,)*9,board=(CHROMA,));self.play(full,DRAW)
        self.assertEqual(len(full.state.players[1].hand),10);self.assertEqual(len(full.state.draw_history),1)
        self.assertEqual(sum(e.card_id==A and e.zone==Zone.GRAVEYARD for e in full.state.entities.values()),1)
        burned=self.game((FILLDRAW,)+(A,)*9,board=(CHROMA,));self.play(burned,FILLDRAW)
        self.assertEqual(len(burned.state.players[1].hand),10);self.assertEqual(burned.state.draw_history[0].outcome,'burned')
        self.assertEqual(sum(e.card_id==A and e.zone==Zone.GRAVEYARD for e in burned.state.entities.values()),1)

    def test_chromaggus_draw_cast_copies_base_and_casts_original_once(self):
        g=self.game((DRAW,),board=(CHROMA,),deck=(CASTER,A));self.play(g,DRAW)
        self.assertEqual(self.hand(g),[CASTER]);self.assertEqual(self.hero(g).armor,1)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(self.entity(g,CASTER).cost,3);self.portable(g)

    def test_chromaggus_wait_keeps_original_material_when_drawn_card_moves(self):
        g=self.game((DRAW,),board=(DRAW_WATCH,CHROMA));self.play(g,DRAW);drawn=g.state.players[1].hand[0]
        g=self.portable(g);self.choose(g,'move')
        self.assertEqual(g.state.entities[drawn].zone,Zone.DECK);self.assertEqual(self.hand(g),[A]);self.portable(g)

    def test_chromaggus_failed_draw_notification_rolls_back_rng_then_copies_once(self):
        g=self.game((DRAW,),board=(DRAW_WATCH,CHROMA));self.play(g,DRAW);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.hand(g),[A,A]);self.portable(g)

    def test_chromaggus_silence_stops_ordinary_draw_copy(self):
        g=self.game((HUSH,DRAW),board=(CHROMA,));self.play(g,HUSH,self.unit(g,CHROMA).id);self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A])

    def test_luna_uses_original_rightmost_before_payload_adds_a_new_card(self):
        g=self.game((NOOP,ADD),board=(LUNA,));self.play(g,ADD)
        self.assertEqual(self.hand(g),[NOOP,A,A]);self.assertEqual(len(g.state.draw_history),1);self.portable(g)

    def test_luna_middle_play_does_not_become_rightmost_after_removal(self):
        g=self.game((NOOP,NOOP),board=(LUNA,));self.play(g,NOOP)
        self.assertEqual(self.hand(g),[NOOP]);self.assertEqual(len(g.state.draw_history),0)

    def test_luna_own_entry_and_opponent_play_are_excluded(self):
        g=self.game((LUNA,),enemy_hand=(NOOP,));self.play(g,LUNA);self.assertEqual(self.hand(g),[])
        self.end(g);self.play(g,NOOP,player=2);self.assertEqual(self.hand(g),[])

    def test_luna_countered_rightmost_play_still_counts_one_physical_play(self):
        g=self.game((NOOP,),board=(LUNA,),enemy=(COUNTER,));self.play(g,NOOP)
        self.assertEqual(self.hand(g),[A]);self.assertTrue(g.state.play_history[-1].countered);self.portable(g)

    def test_luna_spell_repeat_and_automatic_inner_cast_do_not_add_hand_plays(self):
        g=self.game((NOOP,),board=(LUNA,DOUBLE));self.play(g,NOOP)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.cast_history),2)
        g=self.game((AUTO,),board=(LUNA,));self.play(g,AUTO)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_genzo_attack_refills_both_before_combat_with_original_counts(self):
        g=self.game(board=(GENZO,),enemy_hand=(NOOP,));self.attack(g)
        self.assertEqual(self.hand(g),[A]*3);self.assertEqual(self.hand(g,2),[NOOP,A,A]);self.assertEqual(self.hero(g,2).health,25)
        events=g.events;last_draw=max(e.sequence for e in events if e.kind=='card_drawn')
        first_damage=min(e.sequence for e in events if e.kind=='damage_dealt');self.assertLess(last_draw,first_damage);self.portable(g)

    def test_genzo_defending_and_another_attacker_do_not_refill(self):
        g=self.game(board=(GENZO,A),enemy=(A,));self.attack(g,A);self.assertEqual(self.hand(g),[])
        self.end(g);self.assertEqual(self.hand(g,2),[A])
        g.apply(Attack(2,self.unit(g,A,2).id,self.unit(g,GENZO).id))
        self.assertEqual(self.hand(g),[])

    def test_genzo_hands_already_above_three_do_not_draw_or_consume_rng(self):
        g=self.game((A,)*4,board=(GENZO,),enemy_hand=(A,)*3);rng=g._rng.getstate();self.attack(g)
        self.assertEqual(self.hand(g),[A]*4);self.assertEqual(self.hand(g,2),[A]*3)
        self.assertEqual(len(g.state.draw_history),0);self.assertEqual(g._rng.getstate(),rng)

    def test_genzo_original_second_player_gets_its_own_hand_refill(self):
        g=self.game(board=(GENZO,),player=2);self.attack(g,p=2)
        self.assertEqual(self.hand(g,2),[A]*3);self.assertEqual(self.hand(g,1),[A]*3);self.portable(g)

    def test_guarded_double_wait_uses_execution_attack_and_replays_new_payload(self):
        g=self.game((QUEUE,),board=(A,));target=self.unit(g,A).id;self.play(g,QUEUE,target)
        self.assertIn('DoubleCapturedMinionStats',str(g.snapshot()));g=self.portable(g);self.choose(g,'grow')
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(6,40));self.portable(g)

    def test_guarded_double_failed_choice_preserves_original_pending_payload(self):
        g=self.game((QUEUE,),board=(A,));target=self.unit(g,A).id;self.play(g,QUEUE,target);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(g.state.entities[target].attack,2);self.portable(g)

    def test_guarded_double_rejects_bad_selectors_unknown_and_future_references(self):
        g=self.game(board=(A,));ref=MinionReference.capture(self.unit(g,A))
        for kw in ({},{'attack':1},{'attack':True,'beneficiary':{}},
                {'attack':True,'beneficiary':replace(ref,entity_id=999999)},
                {'attack':True,'beneficiary':replace(ref,zone_epoch=ref.zone_epoch+1)},
                {'attack':True,'source_id':999999}):
            values=dict(beneficiary=ref,source_id=ref.entity_id);values.update(kw)
            with self.subTest(values=kw),self.assertRaises(ValueError):DoubleCapturedMinionStats(**values).validate_in_state(g.state)
        codec=FrameCodec(g.mechanics,fixture(),origin_state=g.state,origin_events=g.events)
        effect=DoubleCapturedMinionStats(ref,attack=True,source_id=ref.entity_id);payload=codec.encode(effect)
        self.assertEqual(codec.decode(payload),effect)
        for key,value in(('entity_id',999999),('zone_epoch',ref.zone_epoch+1),('card_id','missing.double.face')):
            forged=deepcopy(payload);forged['fields']['beneficiary']['fields'][key]=value
            with self.subTest(forged=key),self.assertRaises(ValueError):codec.decode(forged)

    def test_standard_host_real_intellect_and_luna_draws_make_six_current_copies(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CHROMA,'CORE_CS2_023'),board=(LUNA,),
            deck=('CORE_CS2_182',)*12,mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*12)),
            generation_context=h.context,seed=688),h.registry)
        self.play(g,CHROMA);self.play(g,'CORE_CS2_023')
        self.assertEqual(self.hand(g),['CORE_CS2_182']*6);self.assertEqual(len(g.state.draw_history),3);self.portable(g)
