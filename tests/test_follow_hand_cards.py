"""Native Follow bodies, physical after-play acceptance and existing delivery."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.follow_hand_cards import (ROOTS,FOOTSTEPS,FUSE,EVIDENCE,GHOSTS,IMP,GHOST,
    BODIES,load_batch,register_follow_hand_cards)
from hs_sim.engine import (CardDefinition,CardType,DamageKind,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.after_play_grants import GrantAfterPlay
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.engine.model import CostSpec
from hs_sim.targets import canonical_digest

P='follow.test.';TINY=P+'tiny';PIRATE=P+'pirate';EXPENSIVE=P+'expensive';CARRIER=P+'carrier'
WAIT=P+'wait';SPELL=P+'spell';WEAPON=P+'weapon';STEALTHS=tuple(P+x for x in ('a','b','c'))
POOL='constructed.cards';TARGET=P+'target'


@lru_cache(maxsize=1)
def full_registry():return assembled_registry()


@lru_cache(maxsize=None)
def registry(role,mode=None,pool_mode=None):
    assert role in ('writer','reader')
    r=build_registry();full=full_registry()
    for cid in (IMP,GHOST):r.register_card(full.card(cid))
    progress=full.card(IMP).hand_progress
    r.register_trigger_condition(progress.condition_id,full.trigger_condition(progress.condition_id))
    r.register_behavior(progress.on_complete,full.behavior(progress.on_complete))
    register_follow_hand_cards(r);meta=replace(r.card('CS2_182').metadata,deck_identity=None)
    def fail(c):raise ResolutionError('Follow deliberate rollback')
    r.register_behavior(P+'fail',fail);r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'draw',lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_behavior(P+'wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(Draw(c.player_id,1,c.source_id),)),
        ChoiceOption('fail','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
            InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),))
    for cid,cost,tribes,keyword,battlecry in (
            (TINY,0,(),(),None),(PIRATE,0,('pirate',),(),None),(EXPENSIVE,9,('pirate',),(),None),
            (CARRIER,1,(),(),P+'draw'),(WAIT,1,(),(),P+'wait'),
            *((cid,i,(),(Keyword.STEALTH,),None)for i,cid in enumerate(STEALTHS))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=3,
            metadata=replace(meta,tribes=tribes),keywords=keyword,battlecry=battlecry))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,metadata=meta))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,on_play=P+'noop',metadata=meta))
    r.register_card(CardDefinition(P+'power',P+'power',CardType.MINION,health=12,spell_damage=6,metadata=meta))
    def stale(c):
        ref=CardReference.capture(c.state.entities[c.target_id])
        return (SummonStoredCard(ref,c.player_id),GrantAfterPlay(ref,BODIES[GHOSTS],c.source_id))
    bodies={
        'stale':stale,
        'attach':lambda c:(GrantAfterPlay(CardReference.capture(c.state.entities[c.target_id]),BODIES[GHOSTS],c.source_id),),
        'discount':lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=0),source_id=c.source_id),),
        'summon':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),),
        'base-copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base'),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
    }
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        zone=Zone.BOARD if key in ('silence','bounce')else Zone.HAND
        r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,
            targeting=TargetSpec(zones=(zone,),kinds=(CardType.MINION,),relation='friendly'),metadata=meta))
    if mode:
        def watch(c):
            if mode in ('counter','counter-carrier'):
                source=c.state.entities.get(c.event.source_id)
                ids=(SPELL,)if mode=='counter-carrier'else(GHOSTS,SPELL)
                return (CounterSpell(dict(c.event.data)['window_id']),)if source and source.card_id in ids else()
            if mode=='grant':
                if dict(c.event.data).get('ability_kind')!='after_play':return ()
            elif mode=='created':
                target=c.state.entities.get(c.event.target_id)
                if target is None or target.card_id not in STEALTHS:return ()
            elif mode=='played':
                record=c.state.play_history[dict(c.event.data)['play_id']-1]
                if not record.after_play:return ()
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',()),
                ChoiceOption('fail','Fail',(AddToHand(c.player_id,TINY,c.source_id),
                    InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
        event={'counter':'card_committed','counter-carrier':'card_committed','grant':'ability_granted',
            'created':'card_created','played':'card_played'}[mode]
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch',P+'watch',CardType.MINION,health=10,
            triggers=(TriggerSpec(event,P+'watch'),),metadata=meta))
    members=[]
    for cid in (STEALTHS if pool_mode!='empty'else()):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)));members.append(PoolMember(cid))
    if pool_mode=='unknown':
        row=replace(r.card(STEALTHS[0]),id=P+'unknown',name=P+'unknown')
        r.register_pool_card(PoolCard.from_definition(row));members.append(PoolMember(row.id))
    r.register_pool(PoolDefinition(POOL,P+'pool-v1',TARGET,'experimental',tuple(members),complete=True))
    r.validate();r.freeze();return r


class FollowHandTests(unittest.TestCase):
    def game(self,hand,*,mana=10,board=(),mode=None,pool_mode=None,enemy_deck=None,seed=236):
        self.mode=mode;self.pool_mode=pool_mode
        own=board+((P+'watch',)if mode else())
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=own,deck=(TINY,)*12,mana=mana,max_mana=10),
            PlayerSetup('HERO_08',deck=(TINY,)*12 if enemy_deck is None else enemy_deck,
                mana=10,max_mana=10)),seed=seed,generation_context=GenerationContext(TARGET,'experimental')),
            registry('writer',mode,pool_mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;i=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,i,target,len(g.state.players[pid].board)if g.registry.card(cid).kind==CardType.MINION else None))
    def hand(self,g,cid):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    def grants(self,g,eid):return [a for a in g.state.entities[eid].abilities if a.kind=='after_play']
    def ghosts(self,g):return [i for i in g.state.players[1].board if g.state.entities[i].card_id==GHOST]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode,self.pool_mode)else'writer',self.mode,self.pool_mode)
        self.assertIsNot(r,g.registry);s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        for v in (other,g.clone(),replay(build_replay(g),r)):self.assertEqual(v.snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('rng_state','resolution_frame','original_entities','"after_play":'):
                self.assertNotIn(field,wire)
        return other
    def test_a00_complete_twelve_raw_rows_twelve_primary_faces_and_reused_tokens(self):
        from tools.card_batch import check_face
        d=load_batch();rows={x['record']['id']:x['record']for k in ('cards','existing_dependencies','evidence_only')for x in d[k]}
        self.assertEqual(len(rows),12);self.assertEqual(len(d['official_observations']),12)
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
        r=registry('writer')
        for cid in (*ROOTS,IMP,GHOST):self.assertEqual(r.card(cid),full_registry().card(cid))
        self.assertEqual([r.card(cid).cost for cid in ROOTS],[1,1,1,2])
        self.assertFalse(any(x['record']['id']in r.cards for x in d['evidence_only']))
    def test_b00_fuse_native_damage_and_actual_pirate_after_play_chain(self):
        g=self.game((FUSE,PIRATE));pirate=self.hand(g,PIRATE)
        first=self.play(g,FUSE);self.assertEqual([e.amount for e in first.events if e.kind=='damage_dealt'],[2])
        self.assertEqual(len(self.grants(g,pirate)),1);second=self.play(g,PIRATE)
        self.assertEqual([e.amount for e in second.events if e.kind=='damage_dealt'],[2])
        self.assertEqual(g.state.play_history[-1].after_play[0].id,self.grants(g,pirate)[0].id)
        self.assertEqual(g.state.players[1].mana,9);self.portable(g)
    def test_b01_fuse_does_not_grant_to_nonpirates_or_unaffordable_current_prices(self):
        g=self.game((FUSE,TINY,EXPENSIVE),mana=2);self.play(g,FUSE)
        self.assertFalse(any(self.grants(g,i)for i in g.state.players[1].hand));self.portable(g)
    def test_b02_fuse_uses_current_discounted_quote_without_consuming_the_discount(self):
        g=self.game((P+'discount',FUSE,EXPENSIVE),mana=1);target=self.hand(g,EXPENSIVE)
        self.play(g,P+'discount',target);self.play(g,FUSE)
        self.assertEqual(len(self.grants(g,target)),1);self.play(g,EXPENSIVE)
        self.assertEqual(g.state.players[1].mana,0);self.portable(g)
    def test_b03_duplicate_hand_cards_are_independent_single_random_recipients(self):
        for seed in (11,42,85):
            with self.subTest(seed=seed):
                g=self.game((FUSE,PIRATE,PIRATE),seed=seed);self.play(g,FUSE)
                ids=[i for i in g.state.players[1].hand if self.grants(g,i)]
                self.assertEqual(len(ids),1);self.assertEqual(g.state.entities[ids[0]].card_id,PIRATE);self.portable(g)
    def test_b04_fuse_inherits_actual_spell_or_minion_damage_kind(self):
        g=self.game((FUSE,PIRATE),board=(P+'power',));first=self.play(g,FUSE)
        self.assertEqual([e.amount for e in first.events if e.kind=='damage_dealt'],[8])
        second=self.play(g,PIRATE)
        self.assertEqual([e.amount for e in second.events if e.kind=='damage_dealt'],[2]);self.portable(g)
    def test_c00_ghosts_regrant_after_actual_battlecry_draw_and_complete_chain(self):
        g=self.game((GHOSTS,CARRIER),mana=3);self.play(g,GHOSTS);carrier=self.hand(g,CARRIER)
        self.assertEqual(len(self.ghosts(g)),1);self.assertEqual(len(self.grants(g,carrier)),1)
        self.play(g,CARRIER);self.assertEqual(len(self.ghosts(g)),2)
        drawn=self.hand(g,TINY);self.assertEqual(len(self.grants(g,drawn)),1)
        self.play(g,TINY);self.assertEqual(len(self.ghosts(g)),3);self.portable(g)
    def test_c01_full_board_does_not_remove_affordable_spell_from_recipient_pool(self):
        g=self.game((GHOSTS,SPELL),board=(TINY,)*7);self.play(g,GHOSTS)
        spell=self.hand(g,SPELL);self.assertEqual(len(self.grants(g,spell)),1)
        self.play(g,SPELL);self.assertFalse(self.ghosts(g));self.portable(g)
    def test_c02_empty_recipient_pool_keeps_rng_and_original_ghost_stats(self):
        g=self.game((GHOSTS,));before=g.snapshot()['rng_state'];self.play(g,GHOSTS)
        self.assertEqual(g.snapshot()['rng_state'],before)
        ghost=g.state.entities[self.ghosts(g)[0]]
        self.assertEqual((ghost.attack,ghost.health),(2,1));self.assertIn(Keyword.REBORN,ghost.keywords);self.portable(g)
    def test_c03_expiry_removes_unused_hand_attachment_at_original_turn_cleanup(self):
        g=self.game((GHOSTS,TINY));self.play(g,GHOSTS);target=self.hand(g,TINY)
        self.assertEqual(len(self.grants(g,target)),1);g.apply(EndTurn(1))
        self.assertFalse(self.grants(g,target));g.apply(EndTurn(2));self.play(g,TINY)
        self.assertEqual(len(self.ghosts(g)),1);self.portable(g)
    def test_c04_weapon_carrier_executes_after_its_normal_equipment_play(self):
        g=self.game((GHOSTS,WEAPON));self.play(g,GHOSTS);weapon=self.hand(g,WEAPON)
        self.play(g,WEAPON);self.assertEqual(g.state.players[1].weapon_id,weapon)
        self.assertEqual(len(self.ghosts(g)),2);self.portable(g)
    def test_c05_turn_expiry_does_not_rewrite_historical_accepted_attachments(self):
        g=self.game((GHOSTS,CARRIER),mana=3);self.play(g,GHOSTS);self.play(g,CARRIER)
        accepted=g.state.play_history[-1].after_play;self.assertEqual(len(accepted),1)
        g.apply(EndTurn(1));self.assertEqual(g.state.play_history[-1].after_play,accepted)
        self.assertFalse(any(self.grants(g,i)for i in (*g.state.players[1].hand,*g.state.players[1].board)))
        self.portable(g)
    def test_d00_evidence_root_and_spell_carrier_use_ordinary_opponent_shuffles(self):
        g=self.game((EVIDENCE,SPELL));self.play(g,EVIDENCE);spell=self.hand(g,SPELL)
        self.assertEqual(len(self.grants(g,spell)),1);self.play(g,SPELL)
        imps=[g.state.entities[i]for i in g.state.players[2].deck if g.state.entities[i].card_id==IMP]
        self.assertEqual(len(imps),2);self.assertTrue(all((e.owner,e.attack,e.health)==(2,3,3)for e in imps))
        self.assertTrue(all(Keyword.LIFESTEAL in e.keywords for e in imps));self.portable(g)
    def test_d01_imp_draw_preserves_opponent_summon_dependency(self):
        g=self.game((EVIDENCE,),enemy_deck=());self.play(g,EVIDENCE);g.apply(EndTurn(1))
        self.assertEqual(sum(g.state.entities[i].card_id==IMP for i in g.state.players[1].board),1)
        self.assertFalse(any(g.state.entities[i].card_id==IMP for i in g.state.players[2].hand));self.portable(g)
    def test_e00_current_copy_keeps_new_attachment_identity_and_plain_copy_drops_it(self):
        g=self.game((P+'attach',TINY,P+'copy',P+'base-copy'));target=self.hand(g,TINY)
        self.play(g,P+'attach',target);original=self.grants(g,target)[0]
        self.play(g,P+'copy',target);self.play(g,P+'base-copy',target)
        copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==TINY and i!=target]
        self.assertEqual(len(copies),2);copied=self.grants(g,copies[0])[0]
        self.assertNotEqual(copied.id,original.id);self.assertEqual(copied.expires_turn,original.expires_turn)
        self.assertFalse(self.grants(g,copies[1]));self.portable(g)
    def test_e01_summoning_is_not_playing_and_silence_or_return_removes_attachment(self):
        for reset in ('silence','bounce'):
            with self.subTest(reset=reset):
                g=self.game((P+'attach',TINY,P+'summon',P+reset));target=self.hand(g,TINY)
                self.play(g,P+'attach',target);self.play(g,P+'summon',target)
                self.assertFalse(self.ghosts(g));self.play(g,P+reset,target)
                self.assertFalse(self.grants(g,target));self.portable(g)
    def test_e02_countered_root_keeps_payment_without_native_body_or_grant(self):
        g=self.game((GHOSTS,TINY),mode='counter');self.play(g,GHOSTS)
        self.assertFalse(self.ghosts(g));self.assertFalse(self.grants(g,self.hand(g,TINY)))
        self.assertEqual(g.state.players[1].mana,8);self.portable(g)
    def test_e03_battlecry_wait_keeps_original_after_play_through_restore_and_failure(self):
        g=self.game((GHOSTS,WAIT),mana=3);self.play(g,GHOSTS);self.play(g,WAIT)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len(self.ghosts(g)),2);self.portable(g)
    def test_e04_post_grant_wait_preserves_hand_attachment_and_failed_choice(self):
        g=self.game((GHOSTS,TINY),mode='grant');self.play(g,GHOSTS)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_e05_completed_countered_carrier_keeps_its_independent_after_play(self):
        g=self.game((GHOSTS,SPELL),mode='counter-carrier');self.play(g,GHOSTS);self.play(g,SPELL)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(len(self.ghosts(g)),2);self.portable(g)
    def test_f00_footsteps_selected_new_entity_has_effect_and_repeats_discovery_after_play(self):
        g=self.game((FOOTSTEPS,));self.play(g,FOOTSTEPS);other=self.portable(g)
        self.assertEqual(len(g.state.pending_choice.options),3)
        key=g.state.pending_choice.options[0].id;self.choose(g,key);self.choose(other,key)
        self.assertEqual(g.snapshot(),other.snapshot());target=g.state.players[1].hand[-1]
        self.assertEqual(len(self.grants(g,target)),1);self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords)
        self.play(g,g.state.entities[target].card_id);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.choose(g,g.state.pending_choice.options[0].id);self.portable(g)
    def test_f01_footsteps_unknown_eligible_candidate_errors_without_clipping_or_rng(self):
        g=self.game((FOOTSTEPS,),pool_mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,FOOTSTEPS)
        self.assertIn(P+'unknown',str(caught.exception))
        self.assertEqual(saved,g.snapshot());self.portable(g)
    def test_f02_footsteps_complete_empty_pool_does_nothing_without_rng(self):
        g=self.game((FOOTSTEPS,),pool_mode='empty');before=g.snapshot()['rng_state'];self.play(g,FOOTSTEPS)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_f03_created_notification_sees_installed_effect_and_restores_pending_delivery(self):
        g=self.game((FOOTSTEPS,),mode='created');self.play(g,FOOTSTEPS)
        self.choose(g,g.state.pending_choice.options[0].id);saved=g.snapshot();other=self.portable(g)
        created=[e for e in g.state.entities.values()if e.card_id in STEALTHS]
        self.assertEqual(len(created),1);self.assertEqual(len(self.grants(g,created[0].id)),1)
        self.assertFalse(created[0].enchantments)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(other.snapshot(),g.snapshot());self.portable(g)
    def test_f04_discovered_effect_expires_without_a_permanent_numeric_marker(self):
        g=self.game((FOOTSTEPS,));self.play(g,FOOTSTEPS)
        self.choose(g,g.state.pending_choice.options[0].id);target=g.state.players[1].hand[-1]
        self.assertEqual(len(self.grants(g,target)),1);self.assertFalse(g.state.entities[target].enchantments)
        g.apply(EndTurn(1));self.assertFalse(self.grants(g,target))
        self.assertFalse(g.state.entities[target].enchantments);self.portable(g)
    def test_g00_rehashed_play_acceptance_rejects_wrong_family_or_expiry_and_old_schema(self):
        g=self.game((GHOSTS,WAIT),mana=3);self.play(g,GHOSTS);self.play(g,WAIT);saved=g.snapshot()
        for key,value in (('kind','on_play'),('expires_turn',g.state.turn+1)):
            bad=deepcopy(saved);bad['state']['play_history'][-1]['after_play'][0][key]=value
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in
                ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry('reader'))
        old=deepcopy(saved);old['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry('reader'))
        self.portable(g)
    def test_g01_captured_hand_reference_does_not_grant_after_summon_departure(self):
        g=self.game((P+'stale',TINY));target=self.hand(g,TINY);result=self.play(g,P+'stale',target)
        self.assertIn(target,g.state.players[1].board);self.assertFalse(self.grants(g,target))
        self.assertTrue(any(e.kind=='zone_target_skipped'for e in result.events));self.portable(g)
    def test_g02_completed_card_played_wait_preserves_typed_after_play_queue(self):
        g=self.game((GHOSTS,SPELL),mode='played');self.play(g,GHOSTS);self.play(g,SPELL)
        self.assertEqual(len(self.ghosts(g)),1);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len(self.ghosts(g)),2);self.portable(g)


if __name__=='__main__':unittest.main()
