"""Actual opening custody, four native portals, weapon kills and original return."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards.broxigar_cards import ROOT,AXE,PORTALS,DEMONS,load_batch,register_broxigar_cards
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardType,DeckPolicy,DeckSpec,EndTurn,
    Game,Keyword,MatchSetup,PlayCard,PlayerSetup,ResolutionError,RewindSpec,Scenario,
    SelectChoice,SnapshotError,SpellSchool,TargetSpec,TriggerSpec,Zone,expand_fabled_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,
    ModifyWeapon,RequestChoice,Silence,Summon)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.vanished_cards import DISAPPEARED,CLAIMED,RETURNED,active_origins
from hs_sim.engine.zones import (CardReference,ChooseFromZone,CopyCard,DrawMatching,
    FillHandWithCard,MoveCard,SetAsideCardReference)
from hs_sim.engine.pools import PoolQuery
from opening_fixtures import metadata,registry as opening_registry

PREP='brox-test.prepare';KILL='brox-test.kill';KILL_RW='brox-test.kill-rewind'
FETCH='brox-test.fetch';COPY='brox-test.copy';THIEF='brox-test.theft';TAKE='brox-test.take'
FILL='brox-test.fill';HURT='brox-test.hurt';WEAR='brox-test.wear';MUTE='brox-test.silence'
REMOVE='brox-test.remove';WATCH='brox-test.watch';WEAK='brox-test.weak';FAT='brox-test.fat'


def fixture(mode='normal'):
    r=opening_registry();register_broxigar_cards(r)
    r.register_card(CardDefinition('dh.power','Explicit DH power',CardType.HERO_POWER,cost=1,
        on_use='power',metadata=metadata(CardClass.DEMON_HUNTER,collectible=False)))
    r.register_card(CardDefinition('dh.hero','Explicit DH hero',CardType.HERO,health=30,
        initial_hero_power='dh.power',metadata=metadata(CardClass.DEMON_HUNTER,collectible=False)))
    def prepare(c):
        p=c.player_id
        if mode=='chain':
            return(DrawMatching(p,PoolQuery(card_ids=(PORTALS[0],)),'skip',source_id=c.source_id),
                *(AddToHand(p,KILL,c.source_id)for _ in range(4)),AddToHand(p,FETCH,c.source_id))
        work=[AddToHand(p,PORTALS[-1],c.source_id)]
        if mode=='burn':work.extend((AddToHand(p,FILL,c.source_id),AddToHand(3-p,KILL,c.source_id)))
        else:work.append(AddToHand(p,KILL_RW if mode=='rewind'else KILL,c.source_id))
        if mode=='copy':work.extend((AddToHand(p,KILL,c.source_id),AddToHand(p,COPY,c.source_id)))
        if mode=='theft':work.extend((AddToHand(p,THIEF,c.source_id),AddToHand(3-p,KILL,c.source_id)))
        if mode=='control':work.append(AddToHand(p,TAKE,c.source_id))
        if mode in('wait','fault'):work.insert(0,Summon(p,WATCH))
        return tuple(work)
    def find_final(c):return next(c.state.entities[eid]for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id==PORTALS[-1])
    def watch(c):
        if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=ROOT:return ()
        if mode=='fault':raise RuntimeError('Explicit hand-return observer failure')
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),source_id=c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,'Explicit return observer '+mode,CardType.MINION,health=100,
        triggers=(TriggerSpec('card_moved_to_hand',WATCH),),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(WEAK,'Explicit small victim',CardType.MINION,health=1,metadata=metadata()))
    r.register_card(CardDefinition(FAT,'Explicit surviving victim',CardType.MINION,health=10,metadata=metadata()))
    scripts={PREP:prepare,KILL:lambda c:(Destroy(c.target_id,c.source_id),),KILL_RW:lambda c:(Destroy(c.target_id,c.source_id),),
        FETCH:lambda c:(DrawMatching(c.player_id,PoolQuery(card_ids=PORTALS),'skip',source_id=c.source_id),AddToHand(c.player_id,FETCH,c.source_id)),
        COPY:lambda c:(CopyCard(CardReference.capture(find_final(c)),c.player_id,source_id=c.source_id),),
        THIEF:lambda c:(CopyCard(CardReference.capture(find_final(c)),3-c.player_id,source_id=c.source_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        MUTE:lambda c:(Silence(c.target_id),),
        FILL:lambda c:(FillHandWithCard(c.player_id,PREP,c.source_id),),
        HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,7,c.source_id),),
        WEAR:lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-1,source_id=c.source_id),),
        REMOVE:lambda c:(RemoveFromGame(tuple(CardReference.capture(c.state.entities[eid])for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id==ROOT),c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);kwargs={}
        if cid in(KILL,KILL_RW,TAKE,MUTE):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if cid==KILL_RW:kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(),**kwargs))
    r.validate();return r


class BroxigarTests(unittest.TestCase):
    def start(self,mode='normal',*,first=1,opening=False,mirror=False):
        r=fixture(mode);own=expand_fabled_cards((ROOT,)+(PREP,)*27,r)
        opponent=(DeckSpec('dh.hero','dh.power',CardClass.DEMON_HUNTER,own)if mirror else
            DeckSpec('mage.hero','mage.power',CardClass.MAGE,tuple(f'card.{i}'for i in range(1,31))))
        decks=(DeckSpec('dh.hero','dh.power',CardClass.DEMON_HUNTER,own),opponent)
        policy=DeckPolicy('brox-explicit-v1','brox-test-target','experimental',tuple(r.cards),max_copies=30)
        g=Game.from_decks(MatchSetup(decks,policy,'coin',172,first),r)
        if not opening:
            while g.state.pending_choice is not None:
                q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def scenario(self,hand=(),*,board=(),enemy=(),deck=(),weapon=None,mode='normal',enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('dh.hero',hand=hand,board=board,deck=deck,
            mana=10,max_mana=10,weapon_card_id=weapon),PlayerSetup('mage.hero',board=enemy,hand=enemy_hand,
            deck=('card.1',)*8,mana=10,max_mana=10)),seed=172),fixture(mode))
    def find(self,g,cid,*,pid=1,zone='hand'):
        return next(g.state.entities[eid]for eid in getattr(g.state.players[pid],zone)if g.state.entities[eid].card_id==cid)
    def play(self,g,cid,*,pid=1,target=None):
        eid=self.find(g,cid,pid=pid).id;g.apply(PlayCard(pid,eid,target));return eid
    def kill(self,g,cid=DEMONS[-1],*,caster=1,owner=2,rewind=False):
        return self.play(g,KILL_RW if rewind else KILL,pid=caster,target=self.find(g,cid,pid=owner,zone='board').id)
    def original(self,g):return next(eid for eid,cid in zip(g.state.opening.original_entities[0],g.state.players[1].original_deck)if cid==ROOT)
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(saved,fixture(mode)).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fixture(mode)).snapshot(),saved)
    def reject(self,saved,mode='normal'):
        saved['events_hash']=canonical_hash(saved['events'])
        if 'vanished_cards'in saved:saved['vanished_cards']['events']=[deepcopy(e)for e in saved['events']if e['kind']in(DISAPPEARED,CLAIMED,RETURNED)]
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,fixture(mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_ten_faces_two_companions_and_four_reviewed_zero_fel_spells(self):
        data=load_batch();r=fixture();self.assertEqual(len(data['official_observations']),20)
        self.assertEqual(r.fabled[ROOT].companion_card_ids,(PORTALS[0],AXE))
        self.assertEqual((r.card(ROOT).cost,r.card(ROOT).attack,r.card(ROOT).health),(2,12,12))
        for cid in PORTALS:self.assertEqual((r.card(cid).cost,r.card(cid).spell_school),(0,SpellSchool.FEL))
        self.assertFalse(data['cn_calibrated'])

    def test_real_opening_disappears_before_mulligan_without_death_or_generation(self):
        for first in(1,2):
            g=self.start(first=first,opening=True);root=self.original(g)
            self.assertEqual(g.state.entities[root].zone,Zone.SETASIDE)
            self.assertNotIn(root,g.state.players[1].deck);self.assertEqual(len(g.state.players[1].original_deck),30)
            self.assertNotIn(root,g.state.opening.offered[0]);self.assertFalse(g.state.death_history)
            self.assertEqual(sum(e.kind==DISAPPEARED for e in g.events),1)
            self.assertEqual(sum(e.card_id==ROOT for e in g.state.entities.values()),1)
            self.portable(g)

    def test_actual_final_demon_returns_same_original_entity_once(self):
        g=self.start();root=self.original(g);self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g)
        self.assertEqual(self.find(g,ROOT).id,root)
        self.assertEqual((g.state.entities[root].owner,g.state.entities[root].controller),(1,1))
        self.assertEqual(sum(e.card_id==ROOT for e in g.state.entities.values()),1)
        self.assertFalse(active_origins(g.events));self.portable(g)

    def test_actual_four_portal_chain_draws_before_shuffle_and_returns_original(self):
        g=self.start('chain');root=self.original(g);self.play(g,PREP)
        for index,(portal,demon)in enumerate(zip(PORTALS,DEMONS)):
            self.play(g,portal);self.assertEqual(self.find(g,demon,pid=2,zone='board').attack,index+1)
            self.kill(g,demon)
            if index<3:
                self.assertEqual(g.state.entities[root].zone,Zone.SETASIDE)
                self.assertTrue(any(g.state.entities[eid].card_id==PORTALS[index+1]for eid in g.state.players[1].deck))
                self.play(g,FETCH)
        self.assertEqual(self.find(g,ROOT).id,root)
        self.assertEqual([d.card_id for d in g.state.death_history if d.card_id in DEMONS],list(DEMONS))
        self.portable(g,'chain')

    def test_printed_intermediate_deathrattle_draws_old_top_then_shuffles_next(self):
        g=self.scenario((PORTALS[0],KILL),deck=(PREP,));old=g.state.players[1].deck[0]
        self.play(g,PORTALS[0]);self.kill(g,DEMONS[0])
        self.assertEqual(self.find(g,PREP).id,old)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].deck],[PORTALS[1]])
        self.assertFalse(any(e.card_id==ROOT for e in g.state.entities.values()));self.portable(g)

    def test_returned_two_mana_body_can_immediately_charge_hero(self):
        g=self.start();self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));source=self.play(g,ROOT)
        victim=g.state.players[2].hero_id;g.apply(Attack(1,source,victim))
        self.assertEqual(g.state.entities[victim].health,18);self.portable(g)

    def test_copied_final_portal_never_creates_second_or_bounces_returned_broxigar(self):
        g=self.start('copy');root=self.original(g);self.play(g,PREP);self.play(g,COPY)
        for _ in range(2):self.play(g,PORTALS[-1]);self.kill(g)
        self.assertEqual(self.find(g,ROOT).id,root)
        self.assertEqual(sum(e.card_id==ROOT for e in g.state.entities.values()),1)
        self.assertEqual(sum(e.kind==CLAIMED for e in g.events),1);self.portable(g,'copy')

    def test_opponent_copy_can_take_original_and_later_original_portal_has_no_reward(self):
        g=self.start('theft');root=self.original(g);self.play(g,PREP);self.play(g,THIEF);g.apply(EndTurn(1))
        self.play(g,PORTALS[-1],pid=2);self.kill(g,caster=2,owner=1)
        self.assertEqual(self.find(g,ROOT,pid=2).id,root)
        self.assertEqual((g.state.entities[root].owner,g.state.entities[root].controller),(1,2))
        g.apply(EndTurn(2));self.play(g,PORTALS[-1]);self.kill(g)
        self.assertFalse(any(g.state.entities[e].card_id==ROOT for e in g.state.players[1].hand))
        self.portable(g,'theft')

    def test_final_demon_current_controller_sets_opposite_recipient(self):
        g=self.start('control');root=self.original(g);self.play(g,PREP);self.play(g,PORTALS[-1])
        target=self.find(g,DEMONS[-1],pid=2,zone='board').id;self.play(g,TAKE,target=target)
        self.kill(g,owner=1)
        self.assertEqual(self.find(g,ROOT,pid=2).id,root);self.portable(g,'control')

    def test_multiple_disappeared_originals_reject_unverified_mirror_selection(self):
        g=self.start(mirror=True);self.play(g,PREP);self.play(g,PORTALS[-1])
        self.assertEqual(len(active_origins(g.events)),2);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'verified mirror source selection'):self.kill(g)
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(e.kind==CLAIMED for e in g.events));self.portable(g)

    def test_full_beneficiary_hand_burns_same_original_and_consumes_custody(self):
        g=self.start('burn');root=self.original(g);self.play(g,PREP);self.play(g,PORTALS[-1]);self.play(g,FILL)
        self.assertEqual(len(g.state.players[1].hand),10);g.apply(EndTurn(1));self.kill(g,caster=2,owner=2)
        self.assertEqual(g.state.entities[root].zone,Zone.GRAVEYARD)
        self.assertFalse(active_origins(g.events));self.assertEqual(sum(e.card_id==ROOT for e in g.state.entities.values()),1)
        self.assertTrue(any(e.kind=='card_burned'and e.target_id==root for e in g.events));self.portable(g,'burn')

    def test_no_actual_disappeared_original_means_no_generated_reward(self):
        g=self.scenario((PORTALS[-1],KILL),deck=(ROOT,));self.play(g,PORTALS[-1]);self.kill(g)
        self.assertEqual(self.find(g,ROOT,zone='deck').zone,Zone.DECK)
        self.assertFalse(any(g.state.entities[e].card_id==ROOT for e in g.state.players[1].hand));self.portable(g)

    def test_generic_removed_broxigar_is_not_native_opening_custody(self):
        g=self.scenario((ROOT,REMOVE,PORTALS[-1],KILL));root=self.find(g,ROOT).id;self.play(g,REMOVE)
        self.play(g,PORTALS[-1]);self.kill(g)
        self.assertEqual(g.state.entities[root].zone,Zone.SETASIDE)
        self.assertNotIn('vanished_cards',g.snapshot());self.portable(g)

    def test_full_opponent_board_does_not_create_a_demon_or_advance_chain(self):
        g=self.scenario((PORTALS[0],),enemy=(WEAK,)*7);self.play(g,PORTALS[0])
        self.assertEqual(len(g.state.players[2].board),7);self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.players[1].deck);self.portable(g)

    def test_silenced_demon_death_does_not_materialize_a_reward(self):
        g=self.scenario((PORTALS[-1],MUTE,KILL));self.play(g,PORTALS[-1]);target=self.find(g,DEMONS[-1],pid=2,zone='board').id
        self.play(g,MUTE,target=target);self.kill(g)
        self.assertFalse(g.state.deathrattle_history);self.assertFalse(any(e.card_id==ROOT for e in g.state.entities.values()))
        self.portable(g)

    def test_original_return_observer_can_wait_restore_and_complete_paid_tail(self):
        g=self.start('wait');root=self.original(g);self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g)
        self.assertEqual(self.find(g,ROOT).id,root);self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertTrue(g.state.play_history[-1].completed);self.portable(g,'wait')

    def test_failed_return_observer_rolls_back_original_rng_claim_and_payment(self):
        g=self.start('fault');self.play(g,PREP);self.play(g,PORTALS[-1]);before=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):self.kill(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)

    def test_rewind_restores_original_custody_and_second_attempt_returns_once(self):
        g=self.start('rewind');root=self.original(g);self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g,rewind=True)
        self.assertEqual(self.find(g,ROOT).id,root);self.portable(g,'rewind')
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('retry',)))
        self.assertEqual(self.find(g,ROOT).id,root)
        self.assertEqual(sum(e.card_id==ROOT for e in g.state.entities.values()),1)
        self.assertEqual(sum(e.kind==CLAIMED for e in g.events),2)
        self.assertEqual(sum(e.kind==CLAIMED for e in __import__('hs_sim.engine.hero_health_history',fromlist=['effective_events']).effective_events(g.events)),1)
        self.portable(g,'rewind')

    def test_axe_genuine_hero_combat_kill_draws_original_portal_and_lifesteals(self):
        g=self.scenario((HURT,),weapon=AXE,enemy=(WEAK,),deck=(PORTALS[0],));portal=g.state.players[1].deck[0]
        self.play(g,HURT);hero=g.state.players[1].hero_id;target=self.find(g,WEAK,pid=2,zone='board').id
        g.apply(Attack(1,hero,target));self.assertEqual(self.find(g,PORTALS[0]).id,portal)
        self.assertEqual(g.state.entities[hero].health,26);self.portable(g)

    def test_axe_last_durability_keeps_actual_kill_reward(self):
        g=self.scenario((WEAR,),weapon=AXE,enemy=(WEAK,),deck=(PORTALS[-1],));self.play(g,WEAR)
        g.apply(Attack(1,g.state.players[1].hero_id,self.find(g,WEAK,pid=2,zone='board').id))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(self.find(g,PORTALS[-1]).card_id,PORTALS[-1]);self.portable(g)

    def test_axe_nonlethal_attack_or_spell_kill_does_not_draw_portal(self):
        g=self.scenario(weapon=AXE,enemy=(FAT,),deck=(PORTALS[0],));g.apply(Attack(1,g.state.players[1].hero_id,self.find(g,FAT,pid=2,zone='board').id))
        self.assertFalse(g.state.players[1].hand);self.portable(g)
        g=self.scenario((KILL,),weapon=AXE,enemy=(WEAK,),deck=(PORTALS[0],));self.kill(g,WEAK)
        self.assertFalse(g.state.players[1].hand);self.portable(g)

    def test_setaside_reference_is_only_explicit_non_draw_return_not_query_or_copy(self):
        ref=SetAsideCardReference(3,1,ROOT,1);work=MoveCard(ref,2,Zone.HAND)
        codec=FrameCodec(default_mechanics(),fixture());self.assertEqual(codec.decode(codec.encode(work)),work)
        with self.assertRaises(ValueError):CardReference(3,1,Zone.SETASIDE,ROOT,1)
        with self.assertRaises(ValueError):ChooseFromZone(1,1,Zone.SETASIDE)
        with self.assertRaises(ValueError):CopyCard(ref,1)
        with self.assertRaises(ValueError):MoveCard(ref,1,Zone.DECK)
        with self.assertRaises(ValueError):MoveCard(ref,1,Zone.HAND,draw=True)

    def test_rehashed_missing_or_altered_original_custody_receipts_reject(self):
        g=self.start();self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g);saved=g.snapshot()
        for kind,key,value in((CLAIMED,'candidates',[]),(CLAIMED,'origin_event',999),(CLAIMED,'origin_event',float(next(e.sequence for e in g.events if e.kind==DISAPPEARED))),
                (RETURNED,'claim_event',True)):
            bad=deepcopy(saved);event=next(e for e in bad['events']if e['kind']==kind);raw=json.loads(event['data']['proof']);raw[key]=value
            event['data']['proof']=json.dumps(raw);self.reject(bad)
        bad=deepcopy(saved);del bad['vanished_cards'];self.reject(bad)

    def test_player_projection_hides_custody_proof_and_internal_original_ids(self):
        g=self.start('wait');self.play(g,PREP);self.play(g,PORTALS[-1]);self.kill(g)
        for pid in(1,2):
            public=json.dumps((g.for_player(pid).observe(),g.for_player(pid).events()),ensure_ascii=False)
            for word in('vanished_cards','origin_event','candidate_events','native_card_disappeared','vanished_card_return_claimed','next_entity_id'):
                self.assertNotIn(word,public)


if __name__=='__main__':unittest.main()
