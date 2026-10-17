"""Real Horn fixed requests, post-summon original recipients and one-turn flags."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.native_outcast_summon_cards import HORN,RAPTOR,ENCHANT,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice)
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Transform
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,SpellRepeatSpec,TargetSpec,Zone
from hs_sim.engine.summon_keyword_groups import GrantOutcastSummonedGroup,OutcastSummonProfile,validate_profile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION,canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k130.test.';YETI='CORE_CS2_182';STUDIES='CORE_YOP_001'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode=None):
    r=build_registry()
    def fail(c):raise ResolutionError('K130 deliberate original group reaction failure')
    def fixed(c):return(SummonByCard(c.player_id,(SummonEntryMaterial(RAPTOR),),SummonCause.capture(c)),)
    scripts={'fail':fail,'natural':fixed,'hit':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'auto':lambda c:(CastSpell(c.player_id,HORN,c.source_id),),
        'reenter':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='hit'else None))
    r.register_card(CardDefinition(P+'repeat','Ordinary shared spell repeat',CardType.MINION,health=8,metadata=META,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    if mode:
        def eligible(c):
            if mode in('grant_wait','grant_fail'):
                return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==HORN
            return any(root.request.cause.source.card_id==HORN and any(d.entity is not None and
                d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode in('summon_fail','grant_fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            target=c.event.target_id
            if mode=='nested':return fixed(c)
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),ChoiceOption('kill','Remove original',(Destroy(target,c.source_id),)),
                ChoiceOption('bounce','Leave original',(ReturnToHand(target),)),
                ChoiceOption('reenter','Reenter original',(ReturnToHand(target),InvokeBehavior(P+'reenter',c.source_id,c.player_id,target))),
                ChoiceOption('give','Transfer original',(ChangeControl(target,2),)),
                ChoiceOption('transform','Transform original',(Transform(target,YETI),)),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        event='ability_granted'if mode in('grant_wait','grant_fail')else'minion_summoned'
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Original group observer',CardType.MINION,health=12,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeOutcastSummonTests(unittest.TestCase):
    def game(self,hand=(HORN,),board=(),enemy=(),mode=None):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10',hand=hand,board=board,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=130),registry(mode))

    def play(self,g,cid=HORN,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid

    def bodies(self,g,source=None):
        return[g.state.entities[x.entity_id]for x in g.state.successful_summon_history if
            x.minion.card_id==RAPTOR and(source is None or any(root.request.cause.source.entity_id==source and
                any(d.entity is not None and(d.entity.entity_id,d.entity.entered_order,d.entity.zone_epoch)==
                    (x.entity_id,x.minion.entered_order,x.minion.zone_epoch)for d in root.deliveries)for root in g.state.card_summon_history))]

    def flags(self,e):return[a for a in e.abilities if a.keyword==Keyword.IMMUNE_WHILE_ATTACKING]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry.__wrapped__(self.mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(self.mode)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('resolution_frame','rng_state','successful_summon_history','card_summon_history','original','attachment_ids'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as e:Game.from_snapshot(saved,registry.__wrapped__(self.mode))
        self.assertNotIn('digest mismatch',str(e.exception))

    def test_complete_three_rows_four_faces_explicit_token_and_printed_flags(self):
        data=load_batch();r=registry();self.assertEqual([len(data[k])for k in('cards','dependencies','evidence_only')],[1,1,1])
        for row in data['cards']+data['dependencies']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        raw={x['record']['id']:x['record']for x in data['cards']+data['dependencies']};norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        observations=data['official_observations']['observations'];self.assertEqual(len(observations),4)
        for ob in observations:
            f=ob['face'];row=raw[ob['card_id']];en=ob['locale']=='en_US';self.assertEqual(norm(f['text']),norm(row['text_en'if en else'text']))
            if ob['card_id']==HORN:self.assertIn(118502,f['childIds'])
        c,t=r.card(HORN),r.card(RAPTOR);self.assertEqual((c.cost,c.metadata.classes,c.keywords),(4,(CardClass.DEMON_HUNTER,),(Keyword.OUTCAST,)))
        self.assertEqual((t.cost,t.attack,t.health,t.metadata.tribes,t.keywords),(2,2,1,('beast',),(Keyword.RUSH,)))
        self.assertFalse(t.metadata.collectible);self.assertNotIn(ENCHANT,r.cards);self.assertNotIn(ENCHANT,r.pool_cards)

    def test_two_defs_one_source_profile_and_old_full_content_preserved(self):
        with patch('hs_sim.cards.native_outcast_summon_cards.register_native_outcast_summon_cards',lambda r:None):old=build_registry()
        new=build_registry();self.assertEqual(set(new.cards)-set(old.cards),{HORN,RAPTOR});self.assertTrue(all(asdict(c)==asdict(new.card(cid))for cid,c in old.cards.items()))
        self.assertEqual({k:v for k,v in new.pool_cards.items()if k!=RAPTOR},dict(old.pool_cards));self.assertEqual(dict(new.generation_families),dict(old.generation_families));self.assertEqual(dict(new.pools),dict(old.pools))
        self.assertEqual(dict(new.outcast_summon_profiles),{HORN:OutcastSummonProfile(HORN,RAPTOR,3)})

    def test_middle_original_position_summons_three_plain_rush_bodies_without_reward(self):
        g=self.game(hand=(YETI,HORN,YETI));source=self.play(g);bodies=self.bodies(g,source)
        self.assertEqual(len(bodies),3);self.assertTrue(all((e.attack,e.health)==(2,1)and Keyword.RUSH in e.keywords and not self.flags(e)for e in bodies))
        self.assertEqual((g.state.players[1].mana,len(g.state.cast_history),len(g.state.card_summon_history)),(36,1,3))

    def test_each_original_hand_edge_grants_exactly_original_three_once(self):
        for hand in((HORN,YETI),(YETI,HORN)):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);source=self.play(g);bodies=self.bodies(g,source)
                self.assertEqual(len(bodies),3);self.assertEqual(len({e.id for e in bodies}),3)
                self.assertTrue(all(len(self.flags(e))==1 and self.flags(e)[0].source_id==source and self.flags(e)[0].expires_turn==g.state.turn for e in bodies))
                self.assertEqual((g.state.players[1].mana,len(g.state.cast_history)),(36,1))
        self.portable(g)

    def test_native_token_and_existing_same_name_never_receive_other_source_reward(self):
        g=self.game(hand=(HORN,P+'natural'),board=(RAPTOR,));old=g.state.players[1].board[0];self.play(g);self.play(g,P+'natural')
        self.assertFalse(self.flags(g.state.entities[old]));self.assertEqual(sum(bool(self.flags(e))for e in self.bodies(g)),3)
        self.assertFalse(self.flags(self.bodies(g)[-1]))

    def test_automatic_cast_does_not_invent_original_outcast_activation(self):
        g=self.game(hand=(P+'auto',));self.play(g,P+'auto');self.assertEqual(len(self.bodies(g)),3)
        self.assertTrue(all(not self.flags(e)for e in self.bodies(g)));self.assertEqual(len(g.state.cast_history),2)

    def test_first_entry_wait_is_before_any_reward_and_remaining_requests_restore(self):
        g=self.game(mode='first_wait');source=self.play(g);self.assertEqual(len(self.bodies(g,source)),1);self.assertFalse(self.flags(self.bodies(g,source)[0]));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.bodies(g,source)),3)
        self.assertTrue(all(len(self.flags(e))==1 for e in self.bodies(g,source)))

    def test_dead_or_departed_original_member_is_skipped_without_selecting_old_same_name(self):
        for key,zone in(('kill',Zone.GRAVEYARD),('bounce',Zone.HAND)):
            with self.subTest(key=key):
                g=self.game(board=(RAPTOR,),mode='first_wait');old=g.state.players[1].board[0];source=self.play(g);first=self.bodies(g,source)[0].id;self.choose(g,key)
                self.assertEqual(g.state.entities[first].zone,zone);self.assertFalse(self.flags(g.state.entities[first]));self.assertFalse(self.flags(g.state.entities[old]))
                self.assertEqual(sum(bool(self.flags(e))for e in self.bodies(g,source)),2)

    def test_same_residence_control_or_transformation_follows_existing_original_entry_guard(self):
        for key in('give','transform'):
            with self.subTest(key=key):
                g=self.game(mode='first_wait');source=self.play(g);first=self.bodies(g,source)[0].id;presence=g.state.entities[first].board_presence_id;self.choose(g,key)
                self.assertEqual(g.state.entities[first].board_presence_id,presence);self.assertTrue(self.flags(g.state.entities[first]));self.assertEqual(self.flags(g.state.entities[first])[0].source_id,source)
                self.assertEqual((g.state.entities[first].controller,g.state.entities[first].card_id),(2,RAPTOR)if key=='give'else(1,YETI))

    def test_same_id_reentry_has_new_residence_and_cannot_steal_original_group_reward(self):
        g=self.game(mode='first_wait');source=self.play(g);first=self.bodies(g,source)[0].id;old=g.state.entities[first].entered_order
        self.choose(g,'reenter');self.assertIn(first,g.state.players[1].board);self.assertNotEqual(g.state.entities[first].entered_order,old)
        self.assertFalse(self.flags(g.state.entities[first]));self.assertEqual(sum(bool(self.flags(e))for e in self.bodies(g,source)),2)

    def test_nested_same_token_is_not_part_of_original_three_requests(self):
        g=self.game(mode='nested');source=self.play(g);self.assertEqual(len(self.bodies(g)),4);self.assertEqual(len(self.bodies(g,source)),3)
        self.assertEqual(sum(bool(self.flags(e))for e in self.bodies(g)),3)

    def test_capacity_zero_or_one_space_keeps_all_original_requests_and_actual_receivers(self):
        for count,expected in((7,0),(6,1)):
            with self.subTest(count=count):
                g=self.game(board=(YETI,)*count);source=self.play(g);bodies=self.bodies(g,source)
                self.assertEqual(len(bodies),expected);self.assertEqual(len(g.state.card_summon_history),3)
                self.assertTrue(all(bool(self.flags(e))for e in bodies));self.assertEqual(g.state.players[1].mana,36)

    def test_immunity_only_during_declared_attack_and_global_end_cleanup(self):
        g=self.game(hand=(HORN,P+'hit'),enemy=(YETI,));source=self.play(g);first=self.bodies(g,source)[0].id;enemy=g.state.players[2].board[0]
        g.apply(Attack(1,first,enemy));self.assertEqual((g.state.entities[first].health,g.state.entities[enemy].health),(1,3))
        self.play(g,P+'hit',first);self.assertEqual(g.state.entities[first].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));self.assertTrue(all(not self.flags(e)for e in self.bodies(g,source)))

    def test_grant_is_one_atomic_group_before_first_grant_reaction_and_restore(self):
        g=self.game(mode='grant_wait');source=self.play(g);self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(len(self.flags(e))==1 for e in self.bodies(g,source)))
        other=self.portable(g)
        for h in(g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(len(self.flags(e))for e in self.bodies(g,source)),3)

    def test_shared_spell_repeat_keeps_each_original_cast_group_separate(self):
        g=self.game(board=(P+'repeat',));source=self.play(g);bodies=self.bodies(g,source)
        self.assertEqual((len(bodies),len(g.state.cast_history),g.state.players[1].mana),(6,2,36));self.assertTrue(all(len(self.flags(e))==1 for e in bodies))

    def test_real_khadgar_quantity_extras_receive_one_reward_each_from_three_original_roots(self):
        g=self.game(board=('CORE_DAL_575',));source=self.play(g);bodies=self.bodies(g,source)
        self.assertEqual(len(bodies),6);self.assertEqual(len(g.state.card_summon_history),3)
        self.assertTrue(all(len(self.flags(e))==1 for e in bodies));self.assertEqual(g.state.players[1].mana,36)
        self.assertTrue(all(len(root.deliveries)==2 for root in g.state.card_summon_history))

    def test_summon_or_grant_reaction_exception_rolls_back_entire_original_spell(self):
        for mode in('summon_fail','grant_fail'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);saved=g.snapshot();rng=g._rng.getstate()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),saved);self.assertEqual(g._rng.getstate(),rng)

    def test_missing_original_request_or_group_continuation_is_rejected_after_rehash(self):
        g=self.game(mode='first_wait');self.play(g);saved=g.snapshot()
        def omit(value,suffix):
            if isinstance(value,dict):
                for x in value.values():
                    if omit(x,suffix):return True
            elif isinstance(value,list):
                for i,x in enumerate(value):
                    if isinstance(x,dict)and x.get('type','').endswith('.'+suffix):value.pop(i);return True
                    if omit(x,suffix):return True
            return False
        for suffix in('SummonByCard','GrantOutcastSummonedGroup'):
            bad=deepcopy(saved);self.assertTrue(omit(bad['resolution_frame'],suffix));self.reject(bad)

    def test_original_caller_flags_or_source_are_not_replaceable_in_saved_group(self):
        g=self.game(mode='first_wait');self.play(g)
        def find(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.GrantOutcastSummonedGroup'):return value['fields']['original']['fields']
                for v in value.values():
                    found=find(v)
                    if found is not None:return found
            elif isinstance(value,list):
                for v in value:
                    found=find(v)
                    if found is not None:return found
        for key,value in(('source_id',99999),('player_id',2)):
            saved=deepcopy(g.snapshot());find(saved['resolution_frame'])[key]=value;self.reject(saved)

    def test_group_tail_cannot_move_before_remaining_original_requests(self):
        g=self.game(mode='first_wait');self.play(g);saved=g.snapshot();work=saved['resolution_frame']['fields']['continuation']['tuple']
        i=next(i for i,w in enumerate(work)if w.get('type','').endswith('.GrantOutcastSummonedGroup'))
        j=next(i for i,w in enumerate(work)if w.get('type','').endswith('.SummonByCard'))
        work.insert(j,work.pop(i));self.reject(saved)

    def test_completed_cast_cannot_lose_private_group_publication_after_rehash(self):
        g=self.game();self.play(g);saved=g.snapshot()
        row=next(e for e in saved['events']if e['kind']=='outcast_summon_group_finished');row['kind']='omitted_private_group'
        saved['events_hash']=canonical_hash(saved['events']);self.reject(saved)

    def test_private_group_publication_keeps_complete_ids_and_native_activation(self):
        g=self.game();self.play(g)
        for key,value in(('summon_ids',()),('outcast',False),('requests',2)):
            saved=g.snapshot();row=next(e for e in saved['events']if e['kind']=='outcast_summon_group_finished')
            row['data'][key]=value
            saved['events_hash']=canonical_hash(saved['events']);self.reject(saved)

    def test_profile_immutable_validation_and_fingerprint_source_binding(self):
        r=build_registry();profile=r.outcast_summon_profiles[HORN]
        with self.assertRaises(TypeError):r.outcast_summon_profiles[HORN]=profile
        with self.assertRaises(ValueError):r.register_outcast_summon_profile(profile)
        for p in(OutcastSummonProfile(STUDIES,RAPTOR,3),OutcastSummonProfile(HORN,HORN,3)):
            with self.assertRaises(ValueError):validate_profile(r,p)
        with self.assertRaises(ValueError):OutcastSummonProfile(HORN,RAPTOR,True)

    def test_previous_schema_rejected_and_original_work_not_in_player_view(self):
        g=self.game(mode='first_wait');self.play(g);self.portable(g);saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__(self.mode))


if __name__=='__main__':unittest.main()
