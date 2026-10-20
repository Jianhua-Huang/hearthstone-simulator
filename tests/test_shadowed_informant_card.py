"""Actual rotating discovery parameter, finite class domain and ordinary offers."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.shadowed_informant_card import CARD,load_batch,register_shadowed_informant_card
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Rarity,Registry,Runes,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.rotating_discovery_classes import CLASSES,VALUES,PUBLICATION,source
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from tools.card_batch import check_face

P='informant.test.'
MAGE,WARRIOR,BLANK,UNIT,WATCH,REPEAT=(P+x for x in ('mage','warrior','blank','unit','watch','repeat'))
CTX=GenerationContext('informant-fixture','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=12)
def registry(mode='plain',role='writer'):
    r=Registry('shadowed-informant-native-v1')
    register_shadowed_informant_card(r)
    for cid,klass in ((MAGE,CardClass.MAGE),(WARRIOR,CardClass.WARRIOR)):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=150,metadata=replace(META,collectible=False,classes=(klass,))))
    r.register_card(CardDefinition(BLANK,BLANK,CardType.SPELL))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=3))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=9,
                                  battlecry_repeats=(BattlecryRepeatSpec(2,(CardType.MINION,)),)))
    members=[]
    for klass in CLASSES:
        for index in range(3):
            cid=P+klass.value+str(index)
            meta=replace(META,classes=(klass,),runes=Runes()if klass==CardClass.DEATH_KNIGHT else None)
            card=CardDefinition(cid,cid,CardType.SPELL,cost=1,metadata=meta)
            r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
            if mode!='empty' or klass!=CardClass.MAGE:members.append(cid)
    if mode=='unknown':
        cid=P+'unadapted';r.register_pool_card(PoolCard(cid,CardType.SPELL,1,replace(META,classes=(CardClass.MAGE,))))
        members.append(cid)
    r.register_pool(PoolDefinition('constructed.cards','v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    scripts=dict(copy=lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        base=lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        give=lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),
        silence=lambda c:(Silence(c.target_id),),change=lambda c:(Transform(c.target_id,UNIT),),
        extra=lambda c:(QueueTurns((c.player_id,),c.source_id),),skip=lambda c:(SkipTurns(3-c.player_id,1,c.source_id),))
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        kw={}if name in ('extra','skip')else dict(targeting=TargetSpec(
            zones=(Zone.BOARD,)if name in ('bounce','silence','change')else(Zone.HAND,),kinds=(CardType.MINION,)))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,target_rule='any_entity',**kw))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('rotation fixture failure')))
    def watch(c):
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode!='wait':return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,triggers=(TriggerSpec(PUBLICATION,P+'watch'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class InformantTests(unittest.TestCase):
    def game(self,hand=(CARD,),board=(),mode='plain',player=1):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(MAGE,hand=hand,board=board,deck=(BLANK,)*12,max_mana=10,mana=10),
            PlayerSetup(WARRIOR,hand=(CARD,)if player==2 else(),deck=(BLANK,)*12,max_mana=10,mana=10)),
            active_player=player,seed=17,generation_context=CTX),registry(mode))

    def eid(self,g,cid,zone='hand',player=None):
        pid=g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        identity=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,identity,target));return identity

    def end(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(g.state.active_player))

    def choose(self,g,key=None):
        q=g.state.pending_choice
        g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id if key is None else key,)))

    def value(self,g,identity=None,player=1):
        return source(g.state.entities[identity if identity is not None else self.eid(g,CARD,player=player)]).discovery_class

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=registry(self.mode,'reader')
        self.assertEqual(Game.from_snapshot(deepcopy(saved),other).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),other).snapshot(),saved)

    def test_a01_full_source_and_both_complete_gallery_templates_stay_strict(self):
        data=load_batch();raw=data['cards'][0]['record'];self.assertEqual(len(data['official_observations']),2)
        for face in data['official_observations']:
            check_face(raw,face['face'],face['locale'],{'@':'','{0}':''})
            bad=deepcopy(face['face']);bad['text']=bad['text'].split('</i>')[0]+'</i>'
            with self.assertRaises(ValueError):check_face(raw,bad,face['locale'],{'@':'','{0}':''})
        bad=deepcopy(raw);bad['text']=bad['text'].replace('法术牌','随从牌')
        with self.assertRaises(ValueError):check_face(bad,data['official_observations'][0]['face'],'zh_CN',{'@':'','{0}':''})

    def test_a02_actual_two_mana_play_discovers_own_initial_class_spell(self):
        g=self.game();identity=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertEqual(g.registry.card(CARD).metadata.classes,(CardClass.NEUTRAL,))
        self.assertEqual(g.state.battlecry_history[-1].payload.discovery_class,'mage')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{P+'mage'+str(i)for i in range(3)})
        self.portable(g);self.choose(g);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(self.value(g,identity),'mage');self.portable(g)

    def test_b01_only_genuine_owner_start_rotates_held_parameter(self):
        g=self.game();identity=self.eid(g,CARD);self.end(g)
        self.assertEqual(self.value(g,identity),'mage');self.end(g)
        self.assertIn(self.value(g,identity),VALUES);self.assertNotEqual(self.value(g,identity),'mage')
        event=next(e for e in g.events if e.kind==PUBLICATION)
        self.assertEqual(len(dict(event.data)['candidates']),10)
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertEqual(g.state.entities[identity].card_id,CARD);self.portable(g)

    def test_b02_rotated_class_filters_the_actual_original_offer(self):
        g=self.game();self.end(g,2);value=self.value(g);self.play(g,CARD)
        self.assertEqual({g.registry.card(o.card_id).metadata.classes[0].value for o in g.state.pending_choice.options},{value})
        self.assertEqual(g.state.battlecry_history[-1].payload.discovery_class,value)
        self.choose(g);self.portable(g)

    def test_b03_deck_source_does_not_tick_before_draw_or_create_fake_randomness(self):
        g=Game.from_scenario(Scenario((PlayerSetup(MAGE,deck=(CARD,BLANK),max_mana=10,mana=10),
            PlayerSetup(WARRIOR,deck=(BLANK,)*6)),generation_context=CTX),registry())
        self.mode='plain';self.end(g)
        self.assertFalse(any(e.kind==PUBLICATION for e in g.events));self.portable(g)

    def test_b04_board_source_keeps_accepted_class_without_future_hand_ticks(self):
        g=self.game();identity=self.play(g,CARD);self.choose(g);self.end(g,2)
        self.assertEqual(self.value(g,identity),'mage')
        self.assertFalse(any(e.kind==PUBLICATION for e in g.events))

    def test_b05_each_physical_held_copy_has_its_own_random_root(self):
        g=self.game((CARD,CARD));self.end(g,2)
        roots=[e for e in g.events if e.kind==PUBLICATION]
        self.assertEqual(len(roots),2);self.assertEqual(len({e.source_id for e in roots}),2)
        self.portable(g)

    def test_c01_current_copy_preserves_parameter_base_copy_uses_recipient_class(self):
        g=self.game((CARD,P+'copy',P+'base'));self.end(g,2);identity=self.eid(g,CARD);value=self.value(g)
        self.play(g,P+'copy',identity);self.play(g,P+'base',identity)
        copies=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD]
        self.assertEqual([source(e).discovery_class for e in copies],[value,value,'mage'])
        self.portable(g)

    def test_c02_transferred_hand_parameter_does_not_rewrite_hero_or_printed_class(self):
        g=self.game((CARD,P+'give'));identity=self.eid(g,CARD)
        self.play(g,P+'give',identity);self.assertEqual(self.value(g,identity),'mage')
        self.end(g);self.assertNotEqual(self.value(g,identity),'mage')
        self.assertEqual(g.state.players[2].hero_class,CardClass.WARRIOR);self.portable(g)

    def test_c03_bounce_rebuilds_native_parameter_and_silence_removes_it(self):
        g=self.game((CARD,P+'bounce',P+'silence'));self.end(g,2)
        identity=self.play(g,CARD);self.choose(g);self.play(g,P+'bounce',identity)
        self.assertEqual(self.value(g,identity),'mage')
        identity=self.play(g,CARD);self.choose(g);self.play(g,P+'silence',identity)
        self.assertIsNone(source(g.state.entities[identity]));self.portable(g)

    def test_c04_transform_retires_old_native_parameter(self):
        g=self.game((CARD,P+'change'));identity=self.play(g,CARD);self.choose(g)
        self.play(g,P+'change',identity);self.assertIsNone(source(g.state.entities[identity]));self.portable(g)

    def test_d01_repeated_battlecry_uses_one_frozen_parameter_and_one_payment(self):
        g=self.game(board=(REPEAT,));self.end(g,2);value=self.value(g);self.play(g,CARD)
        for _ in range(2):
            self.assertEqual({g.registry.card(o.card_id).metadata.classes[0].value for o in g.state.pending_choice.options},{value})
            self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),3)  # One natural draw plus two rewards.
        self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual({b.payload.discovery_class for b in g.state.battlecry_history},{value});self.portable(g)

    def test_d02_rotation_wait_and_failed_selection_are_portable(self):
        g=self.game(board=(WATCH,),mode='wait');self.end(g,2)
        self.assertIsNotNone(g.state.pending_choice);value=self.value(g);before=g.snapshot();self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g,'ok')
        self.assertEqual(self.value(g),value);self.portable(g)

    def test_d03_rotation_failure_rolls_back_turn_parameter_rng_and_history(self):
        g=self.game(board=(WATCH,),mode='fail');self.end(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_d04_empty_pool_is_not_a_fake_offer_and_unknown_candidate_is_not_deleted(self):
        g=self.game(mode='empty');self.play(g,CARD);self.assertIsNone(g.state.pending_choice)
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_e01_extra_turns_tick_once_and_skipped_opponent_slot_is_not_a_tick(self):
        for operation in ('extra','skip'):
            with self.subTest(operation=operation):
                g=self.game((CARD,P+operation));self.play(g,P+operation);self.end(g)
                self.assertEqual(sum(e.kind==PUBLICATION for e in g.events),1)
                self.assertNotEqual(self.value(g),'mage');self.portable(g)

    def test_e02_second_player_starts_from_its_own_actual_hero_class(self):
        g=self.game(hand=(),player=2);self.assertEqual(self.value(g,player=2),'warrior')
        self.play(g,CARD);self.assertEqual(g.state.battlecry_history[-1].payload.discovery_class,'warrior')

    def test_f01_fully_rehashed_parameter_random_domain_and_payload_corruption_reject(self):
        g=self.game();self.end(g,2);identity=self.eid(g,CARD);self.play(g,CARD);saved=g.snapshot()
        for change in ('parameter','candidates','random','payload'):
            bad=deepcopy(saved)
            if change=='parameter':
                native=next(a for a in bad['state']['entities'][str(identity)]['abilities']if a['kind']=='class_discovery')
                native['discovery_class']='mage'
            elif change=='payload':bad['state']['battlecry_history'][-1]['payload']['discovery_class']=None
            else:
                event=next(e for e in bad['events']if e['kind']==PUBLICATION)
                if change=='candidates':event['data']['candidates']=event['data']['candidates'][:-1]
                else:event['data']['selected']='mage'
            with self.subTest(change=change),self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(bad),registry())

    def test_f02_views_expose_owner_parameter_without_receipts_or_enemy_hand(self):
        g=self.game();self.end(g,2);before=g.snapshot()
        own=g.for_player(1).observe()['observation'];enemy=g.for_player(2).observe()['observation']
        slot=next(s for s in own['players'][0]['hand']if s.get('card_id')==CARD)
        self.assertEqual(slot['discover_class'],self.value(g))
        self.assertEqual(g.registry.card(slot['card_id']).metadata.classes,(CardClass.NEUTRAL,))
        self.assertNotIn('discover_class',json.dumps(enemy));self.assertNotIn('rng_before',json.dumps(own))
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
