"""Actual Tranquil Clearing and timed voluntary attacks without dormancy."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_owner_end_sleep_cards import CARD,load_batch,register_native_owner_end_sleep_cards
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Registry,RewindSpec,Scenario,SelectChoice,TargetSpec,TriggerSpec,UseLocation,Zone)
from hs_sim.engine.attack_policies import GrantAttackPolicy,next_owner_end
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,ForceAttack,
    Freeze,GainArmor,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.locations import DestroyLocation,RefreshLocation
from hs_sim.engine.model import AttackPolicySpec,DamageKind,LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.targets import canonical_digest

P='k193.';HERO=P+'hero';BODY=P+'body';CHARGE=P+'charge';RUSH=P+'rush';WATCH=P+'watch';TICK=P+'tick';DORMANT=P+'dormant'


@lru_cache(maxsize=None)
def registry(mode=None):
    r=Registry('k193-owner-end-sleep-'+str(mode));register_native_owner_end_sleep_cards(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=80))
    r.register_card(CardDefinition(BODY,BODY,CardType.MINION,attack=3,health=12))
    for cid,keyword in((CHARGE,Keyword.CHARGE),(RUSH,Keyword.RUSH)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=3,health=12,keywords=(keyword,)))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,attack=3,health=12,dormant_turns=2))
    r.register_behavior(P+'tick',lambda c:(GainArmor(c.player_id,1),)if c.event.player_id==c.player_id else())
    r.register_card(CardDefinition(TICK,TICK,CardType.MINION,attack=3,health=12,triggers=(TriggerSpec('turn_started',P+'tick'),)))
    def rewind(c):
        ref=MinionReference.capture(c.state.entities[c.state.players[c.player_id].board[0]])
        return(GrantAttackPolicy(ref.entity_id,AttackPolicySpec('cannot_attack'),c.source_id,
            recipient=ref,until_next_turn_end=next_owner_end(c.state,c.player_id)),)
    bodies={
        'hit':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'freeze':lambda c:(Freeze(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,2),),
        'force':lambda c:(ForceAttack(c.target_id,c.state.players[2].hero_id),),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'skip':lambda c:(SkipTurns(c.player_id,1,c.source_id),),
        'refresh':lambda c:(RefreshLocation(c.target_id,c.source_id),),
        'rewind':rewind,
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('K193 deliberate failure')),
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        if name=='fail':continue
        fields={}
        if name in('hit','kill','freeze','silence','bounce','give','force'):
            fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if name=='refresh':fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,))
        if name=='rewind':fields.update(rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name,**fields))
    if mode:
        event='turn_ended'if mode=='end_wait'else'attachments_expired'if mode=='expiry_wait'else'stats_changed'
        def eligible(c):
            if event=='turn_ended':return c.event.player_id==c.player_id and sum(x.player_id==c.player_id for x in c.state.owner_turn_history)==2
            if event=='attachments_expired':return c.event.target_id in c.state.players[c.player_id].board
            source=c.state.entities.get(c.event.source_id)
            return(source is not None and source.card_id==CARD and c.event.target_id is not None and
                c.state.entities[c.event.target_id].card_id in(BODY,TICK,CHARGE,RUSH))
        def watch(c):
            original=c.event.target_id
            options=(ChoiceOption('ok','Continue'),ChoiceOption('kill','Remove original minion',
                (Destroy(original,c.source_id),))if original is not None else ChoiceOption('noop','No-op'),
                ChoiceOption('transform','Replace original face',(Transform(original,CHARGE),))if original is not None else ChoiceOption('none','No-op'),
                ChoiceOption('give','Move original minion',(ChangeControl(original,2),))if original is not None else ChoiceOption('stay','No-op'),
                ChoiceOption('fail','Rollback',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))))
            if mode=='failure':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,options,c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeOwnerEndSleepTests(unittest.TestCase):
    def game(self,hand=(CARD,),board=(BODY,),enemy=(),mode=None):
        self.mode=mode
        if mode:board=(*board,WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,board=board,deck=(BODY,)*14,mana=80,max_mana=80,mana_cap=80),
            PlayerSetup(HERO,board=enemy,deck=(BODY,)*14,mana=80,max_mana=80,mana_cap=80)),seed=193),registry(mode))

    def find(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid=CARD,target=None):
        p=g.state.active_player;eid=self.find(g,cid,p,'hand');g.apply(PlayCard(p,eid,target));return eid

    def use(self,g,target=None,location=None):
        location=self.find(g,CARD)if location is None else location
        target=self.find(g,BODY)if target is None else target
        g.apply(UseLocation(g.state.active_player,location,target));return location

    def end(self,g):g.apply(EndTurn(g.state.active_player))

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def clocks(self,g,target):return[a.attack_policy_expiry for a in g.state.entities[target].abilities if a.attack_policy_expiry is not None]

    def assert_cannot_attack(self,g,target,p=1):
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(p,target,g.state.players[3-p].hero_id))
        self.assertEqual(g.snapshot(),before)

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(deepcopy(saved),reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('attack_policy_expiry','until_next_turn_end','resolution_frame','rng_state','MinionReference'):
                self.assertNotIn('"'+key+'"',public)

    def rehash(self,s):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
            'rewind_session','match_setup','generation_context','information')
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:s[k]for k in keys});return s

    def test_real_location_face_metadata_and_both_primary_records(self):
        d=load_batch();raw=d['cards'][0]['record'];card=registry().card(CARD)
        self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        self.assertEqual((card.kind,card.cost,card.durability),(CardType.LOCATION,2,2))
        self.assertEqual(len(d['official_observations']),2)
        self.assertEqual({x['record']['id']for x in d['evidence_only']},{'MEND_044e3','MEND_044e4'})
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_play_then_free_activation_buffs_taunt_and_keeps_minion_active(self):
        g=self.game();target=self.find(g,BODY);loc=self.play(g);self.assertEqual(g.state.players[1].mana,78)
        rng=g.snapshot()['rng_state'];self.use(g,target,loc);e=g.state.entities[target]
        self.assertEqual((e.attack,e.max_health,e.health),(3,14,14));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertTrue(e.active);self.assertIsNone(e.dormancy)
        self.assertEqual((self.clocks(g,target)[0].player_id,self.clocks(g,target)[0].owner_turn_index),(1,2))
        self.assertEqual(g.state.entities[loc].durability,1);self.assertGreater(g.state.entities[loc].location_cooldown,0)
        self.assertEqual(g.state.players[1].mana,78);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse(g.state.cast_history);self.assert_cannot_attack(g,target);self.portable(g)

    def test_expiry_is_next_real_owner_end_not_current_end_or_next_start(self):
        g=self.game();target=self.find(g,BODY);self.play(g);self.use(g)
        self.end(g);self.assertTrue(self.clocks(g,target));self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertTrue(self.clocks(g,target));self.assert_cannot_attack(g,target)
        self.end(g);self.assertFalse(self.clocks(g,target));self.end(g)
        g.apply(Attack(1,target,g.state.players[2].hero_id));self.portable(g)

    def test_enemy_target_uses_activation_player_clock_and_still_defends(self):
        g=self.game(board=(BODY,),enemy=(BODY,));target=self.find(g,BODY,2);self.play(g);self.use(g,target)
        self.assertEqual(self.clocks(g,target)[0].player_id,1);self.end(g)
        self.assert_cannot_attack(g,target,2);self.end(g);self.assertTrue(self.clocks(g,target))
        self.end(g);self.assertFalse(self.clocks(g,target))
        g.apply(Attack(2,target,g.state.players[1].hero_id));self.portable(g)

    def test_asleep_target_remains_spell_targetable_and_taunt_defends(self):
        g=self.game((CARD,P+'hit'),enemy=(BODY,));target=self.find(g,BODY);self.play(g);self.use(g)
        self.play(g,P+'hit',target);self.assertEqual(g.state.entities[target].health,13)
        self.end(g);enemy=self.find(g,BODY,2);g.apply(Attack(2,enemy,target))
        self.assertEqual(g.state.entities[target].health,10);self.assertTrue(self.clocks(g,target));self.portable(g)

    def test_official_forced_attack_path_works_while_voluntary_attack_is_blocked(self):
        g=self.game((CARD,P+'force'));target=self.find(g,BODY);self.play(g);self.use(g)
        self.assert_cannot_attack(g,target);before=g.state.entities[g.state.players[2].hero_id].health
        self.play(g,P+'force',target)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,before-3)
        self.assertTrue(self.clocks(g,target));self.portable(g)

    def test_ongoing_minion_trigger_remains_active_during_sleep(self):
        g=self.game(board=(TICK,));target=self.find(g,TICK);self.play(g);self.use(g,target)
        self.end(g);self.end(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertTrue(self.clocks(g,target));self.portable(g)

    def test_local_charge_and_rush_do_not_clear_the_independent_restriction(self):
        for cid in(CHARGE,RUSH):
            with self.subTest(cid=cid):
                g=self.game(board=(cid,),enemy=(BODY,));target=self.find(g,cid);self.play(g);self.use(g,target)
                self.assert_cannot_attack(g,target)
                with self.assertRaises(IllegalAction):g.apply(Attack(1,target,self.find(g,BODY,2)))
                self.assertIn(Keyword.CHARGE if cid==CHARGE else Keyword.RUSH,g.state.entities[target].keywords)

    def test_location_cooldown_rejects_second_use_without_spending_more(self):
        g=self.game();self.play(g);self.use(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_last_durability_retires_source_but_entire_second_activation_resolves(self):
        g=self.game((CARD,P+'refresh'));target=self.find(g,BODY);loc=self.play(g);self.use(g)
        self.play(g,P+'refresh',loc);self.use(g,target,loc)
        self.assertEqual(g.state.entities[loc].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].max_health,16);self.assertEqual(len(self.clocks(g,target)),2);self.portable(g)

    def test_extra_turn_is_the_actual_next_owner_interval_for_expiry(self):
        g=self.game((CARD,P+'extra'));target=self.find(g,BODY);self.play(g);self.use(g);self.play(g,P+'extra')
        self.end(g);self.assertEqual((g.state.active_player,g.state.turn),(1,2));self.assertTrue(self.clocks(g,target))
        self.end(g);self.assertFalse(self.clocks(g,target));self.portable(g)

    def test_skipped_slot_does_not_advance_the_owner_expiry_clock(self):
        g=self.game((CARD,P+'skip'));target=self.find(g,BODY);self.play(g);self.use(g);self.play(g,P+'skip')
        self.end(g);self.end(g);self.assertEqual(g.state.active_player,2);self.assertTrue(self.clocks(g,target))
        self.end(g);self.assertEqual(g.state.active_player,1);self.assertTrue(self.clocks(g,target))
        self.end(g);self.assertFalse(self.clocks(g,target));self.portable(g)

    def test_control_change_keeps_original_activation_player_deadline(self):
        g=self.game((CARD,P+'give'));target=self.find(g,BODY);self.play(g);self.use(g);self.play(g,P+'give',target)
        self.assertEqual(g.state.entities[target].controller,2);self.assertEqual(self.clocks(g,target)[0].player_id,1)
        self.end(g);self.assert_cannot_attack(g,target,2);self.end(g);self.end(g)
        self.assertFalse(self.clocks(g,target));self.portable(g)

    def test_local_silence_removes_grants_without_resetting_attack_usage(self):
        g=self.game((CARD,P+'silence'));target=self.find(g,BODY)
        g.apply(Attack(1,target,g.state.players[2].hero_id));self.play(g);self.use(g);self.play(g,P+'silence',target)
        self.assertFalse(self.clocks(g,target));self.assertNotIn(Keyword.TAUNT,g.state.entities[target].keywords)
        self.assertEqual(g.state.entities[target].max_health,12);self.assertEqual(g.state.entities[target].attacks_this_turn,1)
        self.assert_cannot_attack(g,target);self.portable(g)

    def test_bounce_clears_original_grants_and_replayed_card_has_no_timer(self):
        g=self.game((CARD,P+'bounce'));target=self.find(g,BODY);self.play(g);self.use(g);self.play(g,P+'bounce',target)
        self.assertFalse(self.clocks(g,target));self.play(g,BODY)
        current=self.find(g,BODY);self.assertFalse(self.clocks(g,current));self.assertEqual(g.state.entities[current].max_health,12);self.portable(g)

    def test_sleep_does_not_modify_existing_frozen_status(self):
        g=self.game((CARD,P+'freeze'));target=self.find(g,BODY);self.play(g,P+'freeze',target)
        self.assertTrue(g.state.entities[target].frozen);self.play(g);self.use(g)
        self.assertTrue(g.state.entities[target].frozen);self.assertTrue(self.clocks(g,target));self.portable(g)

    def test_hero_location_and_dormant_targets_are_rejected_without_using_durability(self):
        g=self.game(board=(BODY,DORMANT));loc=self.play(g)
        for target in(g.state.players[1].hero_id,loc,self.find(g,DORMANT)):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):self.use(g,target,loc)
            self.assertEqual(g.snapshot(),before)

    def test_stats_reaction_wait_keeps_original_target_clock_and_tail(self):
        g=self.game(mode='wait');target=self.find(g,BODY);self.play(g);self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.clocks(g,target));self.portable(g)
        self.choose(g);self.assertEqual(len(self.clocks(g,target)),1);self.portable(g)

    def test_changed_original_target_does_not_receive_later_taunt_or_sleep(self):
        for key in('transform','give','kill'):
            with self.subTest(key=key):
                g=self.game(mode='wait');target=self.find(g,BODY);self.play(g);self.use(g);self.choose(g,key)
                self.assertFalse(self.clocks(g,target));self.assertNotIn(Keyword.TAUNT,g.state.entities[target].keywords);self.portable(g)

    def test_original_activation_failure_restores_durability_stats_and_clock(self):
        g=self.game(mode='failure');self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K193 deliberate'):self.use(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_failed_choice_restores_original_activation_and_rng(self):
        g=self.game(mode='wait');self.play(g);self.use(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K193 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_natural_end_wait_keeps_policy_until_expiry_phase_finishes(self):
        g=self.game(mode='end_wait');target=self.find(g,BODY);self.play(g);self.use(g)
        self.end(g);self.end(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(self.clocks(g,target));self.portable(g)
        self.choose(g);self.assertFalse(self.clocks(g,target));self.portable(g)

    def test_expiry_reaction_observes_all_due_sleep_instances_removed(self):
        g=self.game((CARD,CARD),board=(BODY,BODY),mode='expiry_wait');targets=list(g.state.players[1].board[:2])
        first=self.play(g);self.use(g,targets[0],first);second=self.play(g);self.use(g,targets[1],second)
        self.end(g);self.end(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(all(not self.clocks(g,i)for i in targets));self.portable(g)
        while g.state.pending_choice:self.choose(g)
        self.portable(g)

    def test_death_material_keeps_original_clock_and_restores_after_later_expiry(self):
        g=self.game((CARD,P+'kill'));target=self.find(g,BODY);self.play(g);self.use(g)
        self.play(g,P+'kill',target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        death=g.state.death_history[-1];self.assertEqual(death.entity_id,target)
        self.assertEqual(sum(a.attack_policy_expiry is not None for a in death.abilities),1)
        self.assertEqual(len(self.clocks(g,target)),1);self.portable(g)
        self.end(g);self.end(g);self.end(g)
        self.assertFalse(self.clocks(g,target));self.assertEqual(g.state.death_history[-1],death);self.portable(g)

    def test_actual_rewind_retry_retains_one_policy_with_original_owner_deadline(self):
        g=self.game((P+'rewind',));target=self.find(g,BODY);self.play(g,P+'rewind');self.portable(g)
        self.choose(g,'retry');self.assertEqual(len(self.clocks(g,target)),1)
        self.assertEqual(self.clocks(g,target)[0].owner_turn_index,2);self.portable(g)

    def test_rehashed_future_attachment_deadline_is_rejected(self):
        g=self.game();target=self.find(g,BODY);self.play(g);self.use(g);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(self.rehash(deepcopy(saved)),registry()).snapshot(),saved)
        bad=deepcopy(saved);ability=next(a for a in bad['state']['entities'][str(target)]['abilities']if a['attack_policy_expiry']is not None)
        ability['attack_policy_expiry']['owner_turn_index']+=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry())

    def test_rehashed_future_queued_deadline_is_rejected_before_delivery(self):
        g=self.game(mode='wait');self.play(g);self.use(g);saved=json.loads(json.dumps(g.snapshot()));changed=False
        def alter(node,inside=False):
            nonlocal changed
            if isinstance(node,dict):
                if inside and'owner_turn_index'in node:node['owner_turn_index']+=1;changed=True
                for key,value in node.items():alter(value,inside or key=='until_next_turn_end')
            elif isinstance(node,list):
                for value in node:alter(value,inside)
        alter(saved['resolution_frame']);self.assertTrue(changed)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry(self.mode))

    def test_old_snapshot_schema_is_rejected(self):
        g=self.game();saved=g.snapshot();saved['schema_version']=395
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
