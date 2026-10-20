"""Real Essence sources and original physical cohorts through ordinary casts."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.dragon_soul_essences_cards import CARD,ESSENCES,RED,BLUE,BRONZE,BLACK,GREEN,STORM,DRAGON,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,Game,
    IllegalAction,MatchSetup,PlayCard,PlayerSetup,Rarity,ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.adjoining_spells import PAID,AUTO,ROOT,STEP,END,CastAdjoiningSpells
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.zones import CardReference,MoveCard

P='fixture.essence.';WATCH=P+'watch';FILLER=P+'filler';SPELL=P+'spell';ENEMY=P+'enemy'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
CTX=GenerationContext('dragon-soul-complete-explicit-experiment','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    for cid in(FILLER,ENEMY):
        card=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=12,metadata=META)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,on_play=P+'noop',metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(SPELL)))
    def fail(c):raise ResolutionError('Essence reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'fresh',lambda c:(CastSpell(c.player_id,BLUE,c.source_id),))
    r.register_card(CardDefinition(P+'fresh','Fresh Essence',CardType.SPELL,on_play=P+'fresh'))
    r.register_behavior(P+'stored',lambda c:(CastStoredSpell(CardReference.capture(c.state.entities[c.target_id]),c.player_id,c.source_id),))
    r.register_card(CardDefinition(P+'stored','Stored Essence',CardType.SPELL,on_play=P+'stored',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')))
    for zone in(Zone.HAND,Zone.DECK):
        def foreign(c,zone=zone):
            ids=c.state.players[3-c.player_id].hand if zone==Zone.HAND else c.state.players[3-c.player_id].deck
            entity=next(c.state.entities[i]for i in ids if c.state.entities[i].card_id==BLACK)
            return(CastStoredSpell(CardReference.capture(entity),c.player_id,c.source_id),)
        r.register_behavior(P+'foreign_'+zone.value,foreign)
        r.register_card(CardDefinition(P+'foreign_'+zone.value,'Foreign Essence',CardType.SPELL,on_play=P+'foreign_'+zone.value))
    def watch(c):
        if mode=='counter'and c.event.kind=='card_committed'and c.state.entities[c.event.source_id].card_id in ESSENCES:
            return(CounterSpell(dict(c.event.data)['window_id']),)
        if mode=='move'and c.event.kind=='card_committed'and c.state.entities[c.event.source_id].card_id==BLACK:
            e=next(c.state.entities[i]for i in c.state.players[c.event.player_id].hand if c.state.entities[i].card_id==GREEN)
            return(MoveCard(CardReference.capture(e),c.event.player_id,Zone.DECK,source_id=c.source_id),)
        if (mode=='wait'and c.event.kind=='card_drawn'and c.state.entities[c.event.target_id].card_id==SPELL or
                mode=='child_wait'and c.event.kind=='minion_summoned'and c.state.entities[c.event.target_id].card_id==DRAGON):
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,
        triggers=tuple(TriggerSpec(k,P+'watch')for k in('card_committed','card_drawn','minion_summoned'))))
    r.register_pool(PoolDefinition('essence.fixture.spells','essence-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),PoolMember(SPELL)),complete=True))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class DragonSoulEssenceTests(unittest.TestCase):
    def game(self,hand=ESSENCES,deck=(),enemy=(),mode='normal',active=1,board=(),mana=10,enemy_hand=()):
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==active else enemy_hand,deck=deck,
            board=((WATCH,)if mode in('wait','child_wait')else())+board if p==active else
                ((WATCH,)if mode in('counter','move')else())+enemy,max_mana=mana,mana=mana)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=307,generation_context=CTX),fixture(mode))
    def eid(self,g,card):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==card)
    def play(self,g,card=BLACK,target=None):
        eid=self.eid(g,card);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def armor(self,g,p=None):return g.state.entities[g.state.players[p or g.state.active_player].hero_id].armor
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='normal'):
        saved=g.snapshot();r=fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),r).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        return Game.from_snapshot(saved,r)

    def test_complete_eight_rows_sixteen_primary_faces_and_existing_dragon_pin(self):
        d=load_batch();r=fixture()
        self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(1,6,1,16))
        self.assertEqual((r.card(DRAGON).attack,r.card(DRAGON).health,r.card(DRAGON).metadata.tribes),(8,8,('dragon',)))
        self.assertTrue(all(r.card(c).metadata.classes==(CardClass.NEUTRAL,)for c in(CARD,*ESSENCES)))

    def test_genuine_opening_removes_only_original_root_and_shuffles_six_new_physical_essences(self):
        r=fixture();cards=(CARD,)+(FILLER,)*11
        policy=DeckPolicy('essence.opening',CTX.target_id,CTX.mode,(CARD,FILLER),deck_size=12,max_copies=12)
        setup=MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),policy,'GAME_005',seed=307,first_player=1)
        g=Game.from_decks(setup,r)
        for p in(1,2):
            player=g.state.players[p];self.assertEqual(player.original_deck,cards)
            root=g.state.opening.original_entities[p-1][0];self.assertEqual(g.state.entities[root].zone,Zone.SETASIDE)
            actual=[g.state.entities[i].card_id for i in(*player.deck,*player.hand)]
            self.assertEqual(len(actual),17);self.assertNotIn(CARD,actual)
            for cid in ESSENCES:self.assertEqual(actual.count(cid),1)
        other=self.portable(g)
        for game in(g,other):
            while game.state.pending_choice is not None:
                q=game.state.pending_choice;game.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_source_generated_after_opening_does_not_create_an_extra_start_group(self):
        g=self.game((CARD,));self.play(g,CARD)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(len(g.state.entities),3)
        self.assertFalse(g.state.players[1].deck)

    def test_reviewed_root_hard_generation_ban_keeps_the_complete_pool_inventory(self):
        r=fixture();rows=resolve_candidates(r,CTX,'essence.fixture.spells',PoolQuery(kinds=(CardType.SPELL,),collectible=True))
        self.assertEqual([x.card_id for x in rows],[SPELL]);self.assertIn(CARD,r.pool_cards)

    def test_original_connected_group_pays_once_and_casts_each_physical_essence_once(self):
        g=self.game();original=set(g.state.players[1].hand);self.play(g,BLUE)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),6)
        self.assertEqual({c.source_id for c in g.state.cast_history},original)
        self.assertEqual([c.card_id for c in g.state.cast_history],[BLUE,RED,BRONZE,BLACK,GREEN,STORM])
        self.assertEqual(self.armor(g),12);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[DRAGON])
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in original));self.portable(g)

    def test_non_essence_barrier_keeps_the_other_disconnected_block_in_hand(self):
        g=self.game((GREEN,BLACK,SPELL,STORM,BRONZE));self.play(g)
        self.assertEqual([c.card_id for c in g.state.cast_history],[BLACK,GREEN])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[SPELL,STORM,BRONZE])

    def test_drawn_essences_are_not_recruited_into_the_original_accepted_group(self):
        g=self.game((BLUE,BLACK),deck=(GREEN,STORM,BRONZE));self.play(g,BLUE)
        self.assertEqual([c.card_id for c in g.state.cast_history],[BLUE,BLACK]);self.assertEqual(len(g.state.players[1].hand),3)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand},{GREEN,STORM,BRONZE})

    def test_blue_draws_original_spell_entities_only_and_skips_empty_without_fatigue(self):
        g=self.game((BLUE,),deck=(FILLER,SPELL,BLACK,FILLER));old=set(g.state.players[1].deck);self.play(g,BLUE)
        self.assertTrue(set(g.state.players[1].hand)<=old)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand},{SPELL,BLACK})
        self.assertEqual(len(g.state.players[1].deck),2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_countered_root_does_not_consume_or_cast_any_original_neighbor(self):
        g=self.game((GREEN,BLACK,BRONZE),mode='counter');self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[GREEN,BRONZE])
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.cast_history[0].failure,'countered')
        self.assertEqual(self.armor(g),0);self.assertFalse(any(e.kind==ROOT for e in g.events))

    def test_original_member_moved_before_payload_is_stale_and_never_replaced(self):
        g=self.game((GREEN,BLACK),mode='move');original=self.eid(g,GREEN);self.play(g)
        self.assertEqual(g.state.entities[original].zone,Zone.DECK)
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(self.armor(g),12)
        self.assertEqual(dict(next(e for e in g.events if e.kind==STEP).data)['result'],'stale')

    def test_stored_hand_automatic_cast_uses_its_own_original_cohort_without_extra_paid_plays(self):
        g=self.game((P+'stored',GREEN,BLACK,BRONZE));self.play(g,P+'stored',self.eid(g,BLACK))
        self.assertEqual(len(g.state.play_history),1)
        self.assertEqual([c.card_id for c in g.state.cast_history],[P+'stored',BLACK,GREEN,BRONZE])
        self.assertEqual(self.armor(g),12);self.portable(g)

    def test_generated_automatic_copy_cannot_borrow_essences_already_in_hand(self):
        g=self.game((P+'fresh',BLACK,GREEN),deck=(BRONZE,));self.play(g,P+'fresh')
        self.assertEqual([c.card_id for c in g.state.cast_history],[P+'fresh',BLUE])
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand},{BLACK,GREEN,BRONZE})

    def test_foreign_stored_essence_separates_actor_from_original_hand_owner(self):
        for zone in(Zone.HAND,Zone.DECK):
            with self.subTest(zone=zone):
                card=P+'foreign_'+zone.value
                g=self.game((card,GREEN),deck=(BLACK,)if zone==Zone.DECK else(),
                    enemy_hand=(GREEN,BLACK,BRONZE)if zone==Zone.HAND else())
                original=next(e.id for e in g.state.entities.values()if e.card_id==BLACK and e.controller==2 and e.zone==zone)
                self.play(g,card);self.assertEqual(self.armor(g,1),12);self.assertEqual(self.armor(g,2),0)
                self.assertEqual((g.state.entities[original].owner,g.state.entities[original].controller),(2,1))
                self.assertIn(self.eid(g,GREEN),g.state.players[1].hand)
                self.assertEqual(len(g.state.cast_history),4 if zone==Zone.HAND else 2)
                self.portable(g)

    def test_actual_sinestra_other_class_rule_excludes_all_neutral_essences(self):
        g=self.game((BLACK,GREEN),board=('CATA_154',));self.play(g)
        self.assertEqual([c.card_id for c in g.state.cast_history],[BLACK,GREEN]);self.assertEqual(self.armor(g),12)

    def test_root_draw_reaction_wait_restores_and_resumes_frozen_group_once(self):
        g=self.game((BLACK,BLUE,GREEN),deck=(SPELL,),mode='wait');self.play(g,BLUE)
        saved=g.snapshot();other=self.portable(g,'wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),3);self.assertEqual(self.armor(g),12)

    def test_child_summon_wait_restores_remaining_original_cast_obligation(self):
        g=self.game((GREEN,BLACK,BRONZE),mode='child_wait');self.play(g)
        other=self.portable(g,'child_wait');self.choose(g,'ok');self.choose(other,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),3)

    def test_rehashed_group_crop_member_binding_and_cursor_tampering_are_rejected(self):
        g=self.game((GREEN,BLACK,BRONZE),mode='child_wait');self.play(g);saved=g.snapshot()
        def mutate(value):
            if type(value)is dict:
                if value.get('type','').endswith('CastAdjoiningSpells'):
                    value['fields']['index']+=1;return True
                return any(mutate(x)for x in value.values())
            if type(value)is list:return any(mutate(x)for x in value)
            return False
        for kind in('root','paid','member','cursor'):
            bad=deepcopy(saved)
            if kind=='cursor':
                self.assertTrue(mutate(bad['resolution_frame']))
            else:
                expected={'root':ROOT,'paid':PAID,'member':STEP}[kind]
                next(e for e in bad['events']if e['kind']==expected)['kind']='fixture.cropped_'+kind
            with self.subTest(kind=kind),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('child_wait'))

    def test_second_actor_uses_own_hand_and_armor(self):
        g=self.game((BLACK,GREEN),active=2);self.play(g)
        self.assertEqual(self.armor(g,2),12);self.assertEqual(self.armor(g,1),0)
        self.assertTrue(all(c.player_id==2 for c in g.state.cast_history))

    def test_storm_hits_only_enemy_minions_and_green_uses_original_dragon_body(self):
        g=self.game((STORM,GREEN),enemy=(ENEMY,));enemy=g.state.players[2].board[0];self.play(g,STORM)
        self.assertEqual(g.state.entities[enemy].damage,4);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual((g.state.entities[g.state.players[1].board[0]].attack,g.state.entities[g.state.players[1].board[0]].max_health),(8,8))

    def test_manual_red_requires_an_enemy_target_and_keeps_shared_original_group(self):
        g=self.game((RED,BLACK),enemy=(ENEMY,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,RED,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),saved);target=g.state.players[2].board[0];self.play(g,RED,target)
        self.assertEqual(g.state.entities[target].damage,8);self.assertEqual(self.armor(g),12)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),2)

    def test_private_original_hand_receipts_are_not_published_to_opponent(self):
        g=self.game((BLACK,BLUE,GREEN),deck=(SPELL,),mode='wait');self.play(g,BLUE)
        public=json.dumps(g.observe(2));self.assertNotIn('material_json',public);self.assertNotIn(GREEN,public)
        self.assertNotIn(PAID,public);self.assertNotIn(ROOT,public)


if __name__=='__main__':unittest.main()
