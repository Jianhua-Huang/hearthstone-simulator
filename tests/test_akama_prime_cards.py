"""Permanent native source and the three actual Stealth consumption paths."""
from dataclasses import replace
from functools import lru_cache
import json, unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import akama_prime_cards as native
from hs_sim.engine import Attack, EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario, SnapshotError
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, DestroyBatch, Draw, ForceAttack, GrantKeyword,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, DamageKind, DeathrattleRepeatSpec,
    Keyword, KeywordAuraSpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.registry import Registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format

AKAMA, PRIME = native.AKAMA, native.PRIME
P='k713.'
CLEAR=P+'clear'
DORMANT,AWAKEN=P+'dormant',P+'awaken'
A, B, SHIELD, REPEAT = (P+x for x in ('plain', 'small', 'shield', 'repeat'))
KILL, DRAW, HUSH, RETURN, CONTROL, COPY, FORCE, ABILITY, ZERO, GRANT, MORPH, EARLY, HIT, RANDOM = (
    P+x for x in ('kill', 'draw', 'hush', 'return', 'control', 'copy', 'force', 'ability', 'zero', 'grant', 'morph', 'early', 'hit', 'random'))
WAIT_ATTACK, WAIT_DAMAGE, WAIT_INSERT, FAIL = (P+x for x in ('wait_attack', 'wait_damage', 'wait_insert', 'fail'))
HELPERS=(A,B,SHIELD,REPEAT,KILL,DRAW,HUSH,RETURN,CONTROL,COPY,FORCE,ABILITY,ZERO,GRANT,MORPH,EARLY,HIT,RANDOM,CLEAR,DORMANT,AWAKEN,WAIT_ATTACK,WAIT_DAMAGE,WAIT_INSERT)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,attack,hp,extra in ((A,0,30,{}),(B,1,2,{}),(SHIELD,0,10,dict(keywords=(Keyword.DIVINE_SHIELD,))),
            (REPEAT,0,20,dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=hp,metadata=meta,**extra))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K713 intentional accepted continuation failure')))
    def waiting(c):
        e=c.state.entities.get(c.event.target_id if c.source.card_id==WAIT_INSERT else c.event.source_id)
        if e is None or e.card_id not in (AKAMA,PRIME):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'wait',waiting)
    for cid,event in ((WAIT_ATTACK,'attack_declared'),(WAIT_DAMAGE,'damage_dealt'),(WAIT_INSERT,'card_added_to_deck')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    def source(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in (AKAMA,PRIME))
    bodies={DORMANT:lambda c:(MakeDormant(c.target_id,None,c.source_id),),AWAKEN:lambda c:(AwakenMinion(source(c),c.source_id),),
        CLEAR:lambda c:(DestroyBatch(tuple(i for p in (1,2) for i in c.state.players[p].board),c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),CONTROL:lambda c:(ChangeControl(c.target_id,2),),
        COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id),),
        FORCE:lambda c:(ForceAttack(source(c),c.target_id),),ABILITY:lambda c:(Damage(c.target_id,1,source(c),DamageKind.MINION_ABILITY),),
        ZERO:lambda c:(Damage(c.target_id,0,source(c),DamageKind.MINION_ABILITY),),GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.STEALTH,c.source_id),),
        MORPH:lambda c:(Transform(c.target_id,A),),EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        HIT:lambda c:(Damage(c.target_id,1,c.source_id),),RANDOM:lambda c:(RandomDamage(tuple(c.state.players[2].board),1,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            targeting=None if cid in (DRAW,RANDOM,CLEAR,AWAKEN) else TargetSpec()))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k713-akama-original-native-stealth-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in ('HERO_08','HERO_08bp',*HELPERS):r.register_card(full.card(cid))
    native.register_akama_prime_cards(r);r.validate();return r


class AkamaPrimeTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host' else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),deck=(),watch=None,real_host=False):
        self.mode='host' if real_host else 'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch),PlayerSetup('HERO_08',board=enemy,deck=(B,)*8,mana=40,max_mana=40,
            mana_cap=40,hero_power_card_id='HERO_08bp')),seed=713,generation_context=host().context if real_host else None),
            self.registry_factory(self.mode,'writer'))
    def unit(self,g,cid,player=1):return self.entity(g,cid,player,'board')
    def lost(self,g,eid):return [e for e in g.events if e.kind=='stealth_lost' and e.source_id==eid]
    def hidden(self,g,eid):return Keyword.STEALTH in g.state.entities[eid].keywords
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,15);self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def reject(self,g,edit):
        saved=json.loads(json.dumps(g.snapshot()));edit(saved)
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,self.registry_factory(self.mode,'independent-reader'))

    def test_full_original_faces_native_scope_and_exact_named_Prime_link(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['official_observations']),6);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertFalse(r.card(AKAMA).keyword_auras);self.assertEqual(r.card(PRIME).keyword_auras,(native.PERMANENT,))
        self.assertFalse(r.pool_card(PRIME).metadata.collectible);self.assertIsNone(r.card(PRIME).deathrattle)
        self.assertNotIn('MIS_701',r.cards)

    def test_actual_paid_root_death_shuffle_draw_and_paid_Prime(self):
        g=self.game((AKAMA,KILL,DRAW));eid=self.play(g,AKAMA);self.assertEqual(g.state.players[1].mana,37)
        self.play(g,KILL,eid);prime=self.entity(g,PRIME,zone='deck').id;self.play(g,DRAW);self.assertEqual(self.entity(g,PRIME).id,prime)
        self.play(g,PRIME);self.assertTrue(self.hidden(g,prime));self.assertEqual(g.state.players[1].mana,31);self.portable(g)

    def test_ordinary_attack_keeps_Prime_hidden_and_emits_no_false_loss(self):
        g=self.game(board=(PRIME,),enemy=(B,));eid=self.unit(g,PRIME).id;g.apply(Attack(1,eid,self.unit(g,B,2).id))
        self.assertTrue(self.hidden(g,eid));self.assertEqual(self.lost(g,eid),[]);self.portable(g)

    def test_original_root_still_loses_Stealth_once_on_ordinary_attack(self):
        g=self.game(board=(AKAMA,),enemy=(B,));eid=self.unit(g,AKAMA).id;g.apply(Attack(1,eid,self.unit(g,B,2).id))
        self.assertFalse(self.hidden(g,eid));self.assertEqual(len(self.lost(g,eid)),1);self.portable(g)

    def test_forced_attack_retains_only_the_permanent_native_source(self):
        for cid in (AKAMA,PRIME):
            g=self.game((FORCE,),board=(cid,),enemy=(B,));eid=self.unit(g,cid).id;self.play(g,FORCE,self.unit(g,B,2).id)
            self.assertEqual(self.hidden(g,eid),cid==PRIME);self.assertEqual(len(self.lost(g,eid)),0 if cid==PRIME else 1)
        self.portable(g)

    def test_actual_minion_ability_damage_consumes_only_ordinary_Stealth(self):
        for cid in (AKAMA,PRIME):
            g=self.game((ABILITY,),board=(cid,),enemy=(A,));eid=self.unit(g,cid).id;self.play(g,ABILITY,self.unit(g,A,2).id)
            self.assertEqual(self.hidden(g,eid),cid==PRIME);self.assertEqual(len(self.lost(g,eid)),0 if cid==PRIME else 1)
        self.portable(g)

    def test_zero_or_prevented_minion_ability_damage_does_not_consume_original_flag(self):
        for spell,target in ((ZERO,A),(ABILITY,SHIELD)):
            g=self.game((spell,),board=(AKAMA,),enemy=(target,));eid=self.unit(g,AKAMA).id;self.play(g,spell,self.unit(g,target,2).id)
            self.assertTrue(self.hidden(g,eid));self.assertEqual(self.lost(g,eid),[])

    def test_ordinary_granted_flags_are_consumed_while_native_contribution_remains(self):
        g=self.game((GRANT,GRANT),board=(PRIME,),enemy=(B,));eid=self.unit(g,PRIME).id
        self.play(g,GRANT,eid);self.play(g,GRANT,eid);g.apply(Attack(1,eid,self.unit(g,B,2).id))
        flags=[a for a in g.state.entities[eid].abilities if a.kind=='keyword' and a.keyword==Keyword.STEALTH]
        self.assertEqual(len(flags),3);self.assertTrue(all(a.consumed for a in flags));self.assertTrue(self.hidden(g,eid))
        self.assertEqual(self.lost(g,eid),[]);self.portable(g)

    def test_repeat_turn_attacks_retain_hidden_status_without_resetting_attack_budget(self):
        g=self.game(board=(PRIME,),enemy=(A,),deck=(B,)*3);eid=self.unit(g,PRIME).id;target=self.unit(g,A,2).id
        g.apply(Attack(1,eid,target));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,target))
        self.assertEqual(g.snapshot(),before);g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,eid,target))
        self.assertTrue(self.hidden(g,eid));self.assertEqual(self.lost(g,eid),[])

    def test_enemy_selection_and_attack_cannot_target_permanently_hidden_minion(self):
        g=self.game((KILL,),board=(B,),enemy=(PRIME,));target=self.unit(g,PRIME,2).id
        for action in ('spell','attack'):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):
                if action=='spell':self.play(g,KILL,target)
                else:g.apply(Attack(1,self.unit(g,B).id,target))
            self.assertEqual(g.snapshot(),before)

    def test_random_untargeted_damage_can_hit_Prime_without_removing_its_source(self):
        g=self.game((RANDOM,),enemy=(PRIME,));eid=self.unit(g,PRIME,2).id;self.play(g,RANDOM)
        self.assertEqual(g.state.entities[eid].damage,1);self.assertTrue(self.hidden(g,eid))

    def test_source_silence_reveals_Prime_and_native_material_is_removed(self):
        g=self.game((HUSH,),board=(PRIME,));eid=self.unit(g,PRIME).id;self.play(g,HUSH,eid)
        self.assertFalse(self.hidden(g,eid));self.assertFalse(any(a.kind=='keyword_aura' for a in g.state.entities[eid].abilities));self.portable(g)

    def test_transform_retires_source_and_return_reinstalls_fresh_original_native_declaration(self):
        g=self.game((MORPH,),board=(PRIME,));eid=self.unit(g,PRIME).id;self.play(g,MORPH,eid)
        self.assertEqual(g.state.entities[eid].card_id,A);self.assertFalse(self.hidden(g,eid))
        g=self.game((RETURN,),board=(PRIME,),enemy=(B,));eid=self.unit(g,PRIME).id;g.apply(Attack(1,eid,self.unit(g,B,2).id))
        self.play(g,RETURN,eid);self.play(g,PRIME);self.assertTrue(self.hidden(g,eid));self.portable(g)

    def test_current_copy_keeps_independent_permanent_source_after_original_silence(self):
        g=self.game((COPY,HUSH),board=(PRIME,),enemy=(B,));eid=self.unit(g,PRIME).id;g.apply(Attack(1,eid,self.unit(g,B,2).id))
        original_aura=next(a.id for a in g.state.entities[eid].abilities if a.kind=='keyword_aura')
        self.play(g,COPY,eid);other=next(i for i in g.state.players[1].board if i!=eid)
        self.assertTrue(self.hidden(g,other));self.play(g,HUSH,eid);self.assertFalse(self.hidden(g,eid));self.assertTrue(self.hidden(g,other))
        self.assertNotEqual(next(a.id for a in g.state.entities[other].abilities if a.kind=='keyword_aura'),original_aura);self.portable(g)

    def test_control_transfer_keeps_current_carrier_hidden_under_new_controller(self):
        g=self.game((CONTROL,),board=(PRIME,));eid=self.unit(g,PRIME).id;self.play(g,CONTROL,eid)
        self.assertEqual(g.state.entities[eid].controller,2);self.assertTrue(self.hidden(g,eid));self.portable(g)

    def test_dormancy_pauses_native_source_and_awaken_restores_it_after_flag_consumption(self):
        g=self.game((DORMANT,AWAKEN),board=(PRIME,),enemy=(B,));eid=self.unit(g,PRIME).id
        g.apply(Attack(1,eid,self.unit(g,B,2).id));self.play(g,DORMANT,eid)
        self.assertFalse(self.hidden(g,eid));g=self.portable(g);self.play(g,AWAKEN)
        self.assertTrue(self.hidden(g,eid));self.portable(g)

    def test_root_control_and_silence_preserve_original_upgrade_lifecycle(self):
        g=self.game((AKAMA,CONTROL,CLEAR));eid=self.play(g,AKAMA);self.play(g,CONTROL,eid);self.play(g,CLEAR)
        self.assertEqual(sum(g.state.entities[i].card_id==PRIME for i in g.state.players[2].deck),1)
        self.assertEqual((g.state.deck_shuffle_history[-1].actor_id,g.state.deck_shuffle_history[-1].player_id),(2,2))
        g=self.game((AKAMA,HUSH,KILL));eid=self.play(g,AKAMA);self.play(g,HUSH,eid);self.play(g,KILL,eid)
        self.assertEqual(g.state.players[1].deck,[])

    def test_early_and_repeated_deathrattles_shuffle_exact_Prime(self):
        g=self.game((AKAMA,EARLY,KILL),board=(REPEAT,));eid=self.play(g,AKAMA);self.play(g,EARLY,eid);self.play(g,KILL,eid)
        self.assertEqual(len(g.state.players[1].deck),4);self.assertTrue(all(g.state.entities[i].card_id==PRIME for i in g.state.players[1].deck))
        self.portable(g)

    def test_attack_wait_restores_actual_permanent_source_and_failed_choice_rolls_back(self):
        g=self.game(board=(PRIME,),enemy=(B,),watch=WAIT_ATTACK);eid=self.unit(g,PRIME).id;g.apply(Attack(1,eid,self.unit(g,B,2).id))
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(self.hidden(g,eid));g=self.portable(g);self.fault(g);self.finish(g)
        self.assertTrue(self.hidden(g,eid));self.assertEqual(self.lost(g,eid),[]);self.portable(g)

    def test_minion_ability_damage_wait_restores_without_false_loss_notification(self):
        g=self.game((ABILITY,),board=(PRIME,),enemy=(A,),watch=WAIT_DAMAGE);eid=self.unit(g,PRIME).id;self.play(g,ABILITY,self.unit(g,A,2).id)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertTrue(self.hidden(g,eid));self.assertEqual(self.lost(g,eid),[]);self.portable(g)

    def test_exact_source_profile_rejects_other_targets_conditions_and_dynamic_grants(self):
        self.assertEqual(KeywordAuraSpec(Keyword.STEALTH,target='self'),native.PERMANENT)
        for kw in ({'target':'friendly_minions'},{'target':'self','condition':'self_damaged'},{'target':'self','include_self':True},
                {'target':'self','tribes_any':('draenei',)},{'target':'self','card_ids':(PRIME,)}, {'target':'self','adjacent_only':True}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):KeywordAuraSpec(Keyword.STEALTH,**kw)
        with self.assertRaises(ValueError):GrantKeywordAura(1,native.PERMANENT)

    def test_unrelated_native_face_and_rehashed_snapshot_cannot_substitute_source_scope(self):
        g=self.game(board=(PRIME,));eid=self.unit(g,PRIME).id
        def mutate(saved):
            row=saved['state']['entities'][str(eid)]
            next(a for a in row['abilities'] if a['kind']=='keyword_aura')['keyword_aura']['target']='friendly_minions'
        self.reject(g,mutate)

    def test_old_and_future_snapshot_schemas_are_strictly_rejected(self):
        g=self.game(board=(PRIME,))
        for schema in (1,659,661,True,'660'):
            saved=g.snapshot();saved['schema_version']=schema
            with self.subTest(schema=schema),self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('independent-reader'))

    def test_actual_standard_host_chain_and_permanent_forced_attack(self):
        g=self.game((AKAMA,KILL,DRAW,FORCE),enemy=(B,),real_host=True);eid=self.play(g,AKAMA);self.play(g,KILL,eid)
        self.play(g,DRAW);prime=self.play(g,PRIME);self.play(g,FORCE,self.unit(g,B,2).id)
        self.assertTrue(self.hidden(g,prime));self.assertEqual(self.lost(g,prime),[]);self.portable(g)


if __name__=='__main__':unittest.main()
