"""Real Prepper Outcast, original hero grant and actual own-start retirement."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import re
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.hero_outcast_immunity_cards import PREPPER, IMMUNITY, load_batch
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TimedKeywordSpec
from hs_sim.engine.effects import ChangeControl, ChoiceOption, Damage, Destroy, GrantKeyword, InvokeBehavior, ReplaceHero, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec, Rarity, TargetSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P='k129.test.';YETI='CORE_CS2_182';STUDIES='CORE_YOP_001'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())
CTX=GenerationContext('k129-explicit-real-study','experimental')


@lru_cache(None)
def registry(mode=None):
    r=build_registry()
    r.register_pool(PoolDefinition('constructed.cards','k129-complete-v1',CTX.target_id,CTX.mode,(PoolMember(PREPPER),),complete=True))
    def fail(c):raise ResolutionError('K129 deliberate hero attachment boundary failure')
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'self':lambda c:(Damage(c.state.players[c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),),
        'foe':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),),
        'natural':lambda c:(Summon(c.player_id,PREPPER),),
        'permanent':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id),),
        'replace':lambda c:(ReplaceHero(c.player_id,'HERO_08'),),
        'stealth':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.STEALTH,c.source_id,duration=TimedKeywordSpec(Keyword.STEALTH)),),
        'end':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id,duration=TimedKeywordSpec(Keyword.IMMUNE,'turn_ended')),),
        'opponent':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id,duration=TimedKeywordSpec(Keyword.IMMUNE,player='opponent')),),
        'two':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id,duration=TimedKeywordSpec(Keyword.IMMUNE,occurrences=2)),),
        'unsourced':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,duration=IMMUNITY),),
        'before':lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Grant hero immunity',(
            GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id,duration=IMMUNITY),)),ChoiceOption('skip','Skip')),c.source_id),),
        'fail':fail}
    for name,body in scripts.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','control')else None))
    if mode:
        def eligible(c):
            if mode=='expiry_wait':return c.event.target_id==c.state.players[c.player_id].hero_id
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==PREPPER
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        event='attachments_expired'if mode=='expiry_wait'else'ability_granted'
        r.register_card(CardDefinition(P+'watch','Hero attachment observer',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class HeroOutcastImmunityTests(unittest.TestCase):
    def game(self,hand=(PREPPER,),board=(),enemy_hand=(),mode=None):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10',hand=hand,board=board,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=129,generation_context=CTX),registry(mode))

    def play(self,g,cid=PREPPER,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target,position=len(g.state.players[player].board)if g.state.entities[eid].kind==CardType.MINION else None));return eid

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def flags(self,g,p=1):return[a for a in self.hero(g,p).abilities if a.timed_keyword is not None]
    def immune(self,g,p=1):return Keyword.IMMUNE in self.hero(g,p).keywords
    def turn(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry.__wrapped__(self.mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(self.mode)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('resolution_frame','rng_state','keyword_expiry','created_owner_turn_id','attachment_ids','timed_keyword'):
                self.assertNotIn('"'+field+'"',public)
        return other

    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,registry.__wrapped__(self.mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_real_epic_face_printed_outcast_and_referenced_not_printed_immunity(self):
        data=load_batch();row,=data['cards'];raw=row['record'];c=registry().card(PREPPER)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual((c.cost,c.attack,c.health,c.metadata.classes,c.metadata.tribes,c.metadata.rarity),(5,5,4,(CardClass.DEMON_HUNTER,),(),Rarity.EPIC))
        self.assertEqual(c.keywords,(Keyword.OUTCAST,));self.assertIsNone(c.battlecry);self.assertIsNone(c.spell_school)
        self.assertNotIn('IMMUNE',raw['tags']);self.assertTrue(any(n['tag']=='ReferencedTag'and n['attributes']['name']=='IMMUNE'for n in raw['unmapped_xml_nodes']))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        obs=data['official_observations']['observations'];self.assertEqual(len(obs),2)
        for o in obs:
            en=o['locale']=='en_US';f=o['face'];self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual(f['rarityId'],4)

    def test_register_one_actual_card_preserves_existing_full_content_and_pool_facts(self):
        with patch('hs_sim.cards.hero_outcast_immunity_cards.register_hero_outcast_immunity_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{PREPPER})
        self.assertTrue(all(asdict(c)==asdict(after.card(cid))for cid,c in before.cards.items()))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families))

    def test_actual_left_and_right_outcast_grant_only_hero_and_pay_once(self):
        for hand in((PREPPER,YETI,YETI),(YETI,YETI,PREPPER)):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);source=self.play(g);flag,=self.flags(g)
                self.assertTrue(self.immune(g));self.assertFalse(self.immune(g,2));self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords)
                self.assertEqual((g.state.players[1].mana,len(g.state.play_history),flag.source_id),(35,1,source));self.assertFalse(g.state.battlecry_history)
                self.assertEqual((flag.keyword_expiry.player_id,flag.keyword_expiry.owner_turn_index,flag.keyword_expiry.boundary),(1,2,'turn_started'))
        self.portable(g)

    def test_original_middle_position_has_body_without_reward_or_battlecry(self):
        g=self.game(hand=(YETI,PREPPER,YETI));source=self.play(g)
        self.assertFalse(g.state.play_history[-1].outcast);self.assertFalse(self.immune(g));self.assertFalse(self.flags(g))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.players[1].mana),(5,4,35));self.assertFalse(g.state.battlecry_history)

    def test_natural_summon_never_runs_outcast_onplay_or_rewards(self):
        g=self.game(hand=(P+'natural',));self.play(g,P+'natural');source,=g.state.players[1].board
        self.assertEqual(g.state.entities[source].card_id,PREPPER);self.assertFalse(self.immune(g));self.assertFalse(g.state.battlecry_history)

    def test_immunity_covers_own_and_opponent_turn_then_expires_before_next_own_actions(self):
        g=self.game(hand=(PREPPER,P+'self',P+'self'),enemy_hand=(P+'foe',));self.play(g);self.play(g,P+'self')
        self.assertEqual(self.hero(g).health,30);self.turn(g);self.assertTrue(self.immune(g))
        self.play(g,P+'foe',player=2);self.assertEqual(self.hero(g).health,30);self.turn(g)
        self.assertFalse(self.immune(g));self.assertFalse(self.flags(g));self.play(g,P+'self');self.assertEqual(self.hero(g).health,27)
        self.portable(g)

    def test_source_death_does_not_remove_or_extend_original_hero_deadline(self):
        g=self.game(hand=(PREPPER,P+'kill'));source=self.play(g);expiry=self.flags(g)[0].keyword_expiry
        self.play(g,P+'kill',source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertTrue(self.immune(g));self.assertEqual(self.flags(g)[0].keyword_expiry,expiry)
        self.turn(g);self.assertTrue(self.immune(g));self.turn(g);self.assertFalse(self.immune(g))

    def test_source_transfer_does_not_reassign_hero_or_its_clock(self):
        g=self.game(hand=(PREPPER,P+'control'));source=self.play(g);expiry=self.flags(g)[0].keyword_expiry
        self.play(g,P+'control',source);self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(self.flags(g)[0].keyword_expiry,expiry)
        self.assertTrue(self.immune(g));self.assertFalse(self.immune(g,2));self.turn(g);self.turn(g);self.assertFalse(self.immune(g))

    def test_hero_replacement_keeps_original_deadline_and_fresh_attachment_identity(self):
        g=self.game(hand=(PREPPER,P+'replace'));self.play(g);old=self.hero(g).id;flag=self.flags(g)[0]
        self.play(g,P+'replace');new=self.hero(g).id;copied,=self.flags(g)
        self.assertNotEqual(old,new);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertNotEqual(copied.id,flag.id)
        self.assertEqual((copied.source_id,copied.keyword_expiry),(flag.source_id,flag.keyword_expiry));self.assertTrue(self.immune(g));self.portable(g)
        self.turn(g);self.turn(g);self.assertFalse(self.immune(g));self.assertFalse(any(a.timed_keyword is not None for a in g.state.entities[old].abilities))

    def test_retirement_removes_only_timed_grant_and_keeps_ordinary_permanent_immunity(self):
        g=self.game(hand=(PREPPER,P+'permanent'));self.play(g);self.play(g,P+'permanent')
        self.assertEqual(len(self.flags(g)),1);self.turn(g);self.turn(g);self.assertTrue(self.immune(g));self.assertFalse(self.flags(g))

    def test_only_real_hero_duration_profile_is_supported_and_others_rollback(self):
        for name in('stealth','end','opponent','two','unsourced'):
            with self.subTest(name=name):
                g=self.game(hand=(P+name,));saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,P+name)
                self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ValueError):build_registry().register_card(CardDefinition(P+'printed','No printed hero timer',CardType.HERO,health=30,keywords=(Keyword.IMMUNE,),timed_keywords=(IMMUNITY,)))

    def test_real_studies_can_discover_discount_and_play_new_outcast_root(self):
        g=self.game(hand=(STUDIES,));self.play(g,STUDIES);q=g.state.pending_choice
        self.assertEqual(len(q.options),1);self.assertEqual(q.options[0].card_id,PREPPER);self.choose(g,q.options[0].id)
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==PREPPER);self.assertEqual(g.quote_cost(eid).amount,4)
        self.play(g);self.assertTrue(self.immune(g));self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(g.state.players[1].mana,35)
        self.portable(g)

    def test_actual_grant_wait_restores_original_deadline_and_failure_keeps_boundary(self):
        g=self.game(mode='grant_wait');self.play(g);self.assertIsNotNone(g.state.pending_choice);self.assertTrue(self.immune(g));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.flags(g)),1)

    def test_expiry_wait_occurs_after_removal_before_next_draw_and_is_resumable(self):
        g=self.game(mode='expiry_wait');self.play(g);self.turn(g);draws=len(g.state.draw_history);self.turn(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.immune(g));self.assertEqual(len(g.state.draw_history),draws)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),draws+1)

    def test_grant_reaction_error_rolls_back_payment_body_allocation_and_clock(self):
        g=self.game(mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_saved_hero_duration_requires_original_typed_profile_source_and_deadline(self):
        g=self.game();self.play(g);hero=self.hero(g).id
        for key,value in(('keyword_expiry',None),('source_id',None),('origin','printed')):
            saved=deepcopy(g.snapshot());row=next(a for a in saved['state']['entities'][str(hero)]['abilities']if a['timed_keyword']is not None);row[key]=value
            with self.subTest(key=key):self.reject(saved)
        for key,value in(('owner_turn_index',3),('player_id',2),('created_turn',2)):
            saved=deepcopy(g.snapshot());row=next(a for a in saved['state']['entities'][str(hero)]['abilities']if a['timed_keyword']is not None);row['keyword_expiry'][key]=value
            with self.subTest(key=key):self.reject(saved)

    def test_pending_hero_grant_branch_roundtrips_existing_request(self):
        g=self.game(hand=(P+'before',));self.play(g,P+'before');self.assertFalse(self.immune(g));other=self.portable(g)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(self.immune(g));self.turn(g);self.turn(g);self.assertFalse(self.immune(g))

    def test_both_players_see_only_public_immunity_deadline_and_previous_schema_is_rejected(self):
        g=self.game();self.play(g);expiry=self.flags(g)[0].keyword_expiry
        for p in(1,2):
            observation=g.for_player(p).observe()['observation'];hero=next(x for x in observation['players']if x['id']==1)['hero']
            self.assertIn('immune',hero['keywords']);self.assertEqual(hero['keyword_durations'],[dict(keyword='immune',boundary='turn_started',player_id=1,owner_turn_index=expiry.owner_turn_index)])
        self.portable(g);saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__(self.mode))


if __name__=='__main__':unittest.main()
