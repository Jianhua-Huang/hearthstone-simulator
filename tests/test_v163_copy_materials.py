"""Native immutable physical copy recipes, real checkpoints and portability."""
from copy import deepcopy
from dataclasses import replace
import json,unittest

from hs_sim.engine import (AttackPolicySpec,AuraSpec,BuffStoredCard,CardDefinition,CardType,Game,Keyword,PlayerSetup,
    PrintedAttackPolicyDeclaration,GrantPrintedAttackPermit,RewindSpec,Scenario,SnapshotError,
    SummonCause,SummonStats,TriggerSpec,Zone,capture_printed_attack_permit)
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Damage,Destroy,EquipWeapon,Freeze,
    GainArmor,GrantDeathrattle,GrantKeyword,RandomDamage,RequestChoice,Silence,Transform)
from hs_sim.engine.dormancy import AwakenMinion
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
import test_v160_summon_quantities as base


def registry():
    r=base.registry()
    def copy(c,mode='current',player=1,position=None):
        return CopyMinion(c.target_id,player,position,mode,SummonCause.capture(c))
    def ref(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id in ('body','cx_dormant')))
    def stored(c,mode='current',stats=None):
        return CopyStoredMinion(ref(c),1,mode=mode,stats=stats,cause=SummonCause.capture(c))
    def prep(c):
        return [Buff(c.target_id,3,2,c.source_id),GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),
            Damage(c.target_id,1,c.source_id),Damage(c.target_id,2,c.source_id),
            GrantDeathrattle(c.target_id,'gift',c.source_id),Freeze(c.target_id),copy(c)]
    def watch(c):
        roots=c.state.card_summon_history
        if not roots or not roots[-1].deliveries or roots[-1].deliveries[-1].index!=0:return []
        material=roots[-1].request.materials[0]
        if not hasattr(material,'profile'):return []
        sources=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='source']
        return [Transform(material.origin.entity_id,'other'),*(Destroy(i,c.source_id)for i in sources),
            Buff(c.event.target_id,10,0,c.source_id),RequestChoice(1,(
                ChoiceOption('bad','Rollback',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'body'))),
                ChoiceOption('ok','Continue',())),c.source_id)]
    r.register_behavior('cx_watch',watch)
    r.register_card(CardDefinition('cx_watch','Change original after first copy',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_summoned','cx_watch'),)))
    r.register_behavior('cx_nested_watch',lambda c:[]if len(c.state.card_summon_history)!=1 else[CastSpell(1,'cx_stored',c.source_id,choices='player')])
    r.register_card(CardDefinition('cx_nested_watch','Nested stored copy',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_summoned','cx_nested_watch'),)))
    r.register_card(CardDefinition('cx_dormant','Dormant copy face',CardType.MINION,attack=2,health=5,dormant_turns=2))
    r.register_card(CardDefinition('cx_banned','Printed restriction',CardType.MINION,attack=2,health=5,
        attack_policies=(AttackPolicySpec('cannot_attack'),)))
    r.register_card(CardDefinition('cx_aura','Derived external contribution',CardType.MINION,health=5,auras=(AuraSpec(attack=4,health=3),)))
    def permit(c):
        req=capture_printed_attack_permit(c.state,r,c.target_id,PrintedAttackPolicyDeclaration('cx_banned',0))
        return [GrantPrintedAttackPermit(req),copy(c)]
    def stale(c):
        original=stored(c)
        return [MoveCard(original.card,1,Zone.DECK,position='bottom'),original]
    bodies={
        'cx_current':lambda c:[copy(c)],'cx_base':lambda c:[copy(c,'base')],
        'cx_enemy':lambda c:[copy(c,player=2)],'cx_position':lambda c:[copy(c,position=0)],
        'cx_prepped':prep,'cx_silenced':lambda c:[Buff(c.target_id,3,2),Silence(c.target_id),copy(c)],
        'cx_qty_next':lambda c:[copy(c),base.SummonByCard(1,(base.SummonEntryMaterial('body'),),SummonCause.capture(c))],
        'cx_stored':lambda c:[stored(c)],'cx_stored_base':lambda c:[stored(c,'base')],
        'cx_stored_stats':lambda c:[BuffStoredCard(ref(c),3,2),stored(c,stats=SummonStats(9,2))],
        'cx_stored_current':lambda c:[BuffStoredCard(ref(c),3,2),stored(c)],
        'cx_stale':stale,'cx_stale_board':lambda c:[Destroy(c.target_id),copy(c)],
        'cx_wait':lambda c:[RequestChoice(1,(ChoiceOption('ok','Copy',(copy(c),)),),c.source_id)],
        'cx_retry':lambda c:[copy(c)],'cx_permit':permit,
        'cx_temporary':lambda c:[CreateTemporaryCard(1,'body',c.state.turn,source_id=c.source_id)],
        'cx_awake_copy':lambda c:[AwakenMinion(c.state.players[1].board[1]),CopyMinion(c.state.players[1].board[1],1,cause=SummonCause.capture(c))],
    }
    targets={'cx_current','cx_base','cx_enemy','cx_position','cx_prepped','cx_silenced','cx_qty_next','cx_stale_board','cx_wait','cx_retry','cx_permit'}
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in targets,keywords=(Keyword.REWIND,)if name=='cx_retry'else(),rewind=RewindSpec(1)if name=='cx_retry'else None))
    return r


class CopyMaterialTests(unittest.TestCase):
    blob=base.SummonQuantityTests.blob
    play=base.SummonQuantityTests.play
    choose=base.SummonQuantityTests.choose
    def game(self,hand=(),board=(),enemy=()):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('body',)*5)),seed=163),registry())
        self.blob(g,'initial');return g
    def copies(self,g,index=-1):
        return [g.state.entities[d.entity.entity_id]for d in g.state.card_summon_history[index].deliveries if d.entity]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for player in (1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('CopyEntryMaterial','CopyLocalState','card_summon_history','card_summon_accepted','card_summon_finished','rng_before','rng_after'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def reject(self,s,label):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s,label)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_current_keeps_local_damage_consumption_freeze_and_new_attachments(self):
        g=self.game(('cx_prepped',),('source','body'));original=g.state.players[1].board[1];self.play(g,'cx_prepped',original)
        copies=self.copies(g);self.assertEqual(len(copies),2)
        for e in copies:
            self.assertEqual((e.attack,e.max_health,e.damage,e.health,e.origin_entity_id),(5,7,2,5,original))
            self.assertTrue(e.frozen);self.assertNotIn(Keyword.DIVINE_SHIELD,e.keywords)
            self.assertTrue(next(a for a in e.abilities if a.keyword==Keyword.DIVINE_SHIELD).consumed)
        all_ids=[a.id for e in (*copies,g.state.entities[original])for a in (*e.enchantments,*e.abilities)]
        self.assertEqual(len(all_ids),len(set(all_ids)));self.portable(g)

    def test_base_rebuilds_definition_and_does_not_borrow_current_attachments(self):
        g=self.game(('cx_prepped','cx_base'),('source','body'));original=g.state.players[1].board[1]
        self.play(g,'cx_prepped',original);self.play(g,'cx_base',original)
        for e in self.copies(g):self.assertEqual((e.attack,e.health,e.damage,e.frozen,len(e.enchantments)),(2,5,0,False,0))
        self.assertIsNone(g.state.card_summon_history[-1].request.materials[0].local);self.portable(g)

    def test_silenced_copy_stays_silenced_but_base_is_printed(self):
        g=self.game(('cx_silenced','cx_base'),('source','source'));original=g.state.players[1].board[1]
        self.play(g,'cx_silenced',original);self.assertTrue(all(e.silenced for e in self.copies(g)))
        self.assertTrue(all(not any(a.kind=='summon_quantity'for a in e.abilities)for e in self.copies(g)))
        self.play(g,'cx_base',original);self.assertTrue(all(not e.silenced for e in self.copies(g)))
        self.assertTrue(all(any(a.kind=='summon_quantity'for a in e.abilities)for e in self.copies(g)));self.portable(g)

    def test_accepted_material_survives_original_transform_and_real_wait(self):
        g=self.game(('cx_current','cx_base'),('source','body','cx_watch'));original=g.state.players[1].board[1]
        self.play(g,'cx_current',original);s=self.portable(g);root=g.state.card_summon_history[-1]
        self.assertEqual((root.plan.total,len(root.deliveries)),(2,1));self.assertEqual(g.state.entities[original].card_id,'other')
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual([(e.card_id,e.attack)for e in self.copies(g)],[('body',12),('body',2)]);self.portable(g)
        self.play(g,'cx_base',original);self.assertEqual(g.state.card_summon_history[-1].plan.total,1)
        self.choose(g,'ok');self.assertEqual(self.copies(g)[0].card_id,'other');self.portable(g)

    def test_copied_quantity_printed_self_is_new_identity_and_next_root_recaptures(self):
        g=self.game(('cx_qty_next',),('source',));original=g.state.players[1].board[0];self.play(g,'cx_qty_next',original)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,8])
        for e in self.copies(g,0):
            a=next(a for a in e.abilities if a.kind=='summon_quantity');self.assertEqual(a.source_id,e.id)
        self.assertEqual(g.state.card_summon_history[0].request.materials[0].origin.entity_id,original);self.portable(g)

    def test_cross_owner_and_recipient_use_causing_player_quantity(self):
        g=self.game(('cx_enemy',),('source',),('body',));original=g.state.players[2].board[0]
        self.play(g,'cx_enemy',original);root=g.state.card_summon_history[-1]
        self.assertEqual((root.plan.total,root.request.cause.player_id,root.request.player_id),(2,1,2))
        self.assertTrue(all((e.owner,e.controller,e.origin_entity_id)==(2,2,original)for e in self.copies(g)));self.portable(g)

    def test_position_cursor_orders_copies_at_original_insertion(self):
        g=self.game(('cx_position',),('source','body'));original=g.state.players[1].board[1];self.play(g,'cx_position',original)
        ids=[e.id for e in self.copies(g)];self.assertEqual(g.state.players[1].board[:2],ids);self.portable(g)

    def test_full_board_profiles_keep_distinct_gameplay_events_and_no_rng(self):
        for name,targeted in (('cx_current',True),('cx_stored',False)):
            with self.subTest(name=name):
                g=self.game((name,'body'),('source',)+('body',)*6);before=g.snapshot()['rng_state']
                self.play(g,name,g.state.players[1].board[1]if targeted else None);root=g.state.card_summon_history[-1]
                self.assertEqual((root.status,root.selected,root.deliveries),('skipped',None,()))
                self.assertEqual(g.snapshot()['rng_state'],before)
                self.assertEqual(sum(e.kind=='summon_failed'for e in g.events),1 if targeted else 0);self.portable(g)

    def test_stored_current_keeps_local_buff_without_moving_original(self):
        g=self.game(('cx_stored_current','body'),('source',));original=g.state.players[1].hand[-1]
        self.play(g,'cx_stored_current');self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertEqual([(e.attack,e.health,e.origin_entity_id)for e in self.copies(g)],[(5,7,original)]*2);self.portable(g)

    def test_stored_stats_override_each_independent_entry(self):
        g=self.game(('cx_stored_stats','body'),('source',));self.play(g,'cx_stored_stats')
        self.assertEqual([(e.attack,e.health,e.damage)for e in self.copies(g)],[(9,2,0)]*2)
        ids=[a.id for e in self.copies(g)for a in e.enchantments];self.assertEqual(len(ids),len(set(ids)));self.portable(g)

    def test_external_aura_cache_is_recomputed_for_receiving_player(self):
        g=self.game(('cx_enemy',),('source','body','cx_aura'));original=g.state.players[1].board[1]
        self.assertEqual((g.state.entities[original].attack,g.state.entities[original].max_health),(6,8))
        self.play(g,'cx_enemy',original)
        self.assertEqual([(e.attack,e.health)for e in self.copies(g)],[(2,5)]*2)
        material=g.state.card_summon_history[-1].request.materials[0]
        self.assertEqual((material.local.base_attack,material.local.base_health,material.local.enchantments),(2,5,()))
        self.portable(g)

    def test_stored_base_resets_prior_stored_local_buffs(self):
        g=self.game(('cx_stored_current','cx_stored_base','body'),('source',));self.play(g,'cx_stored_current')
        self.play(g,'cx_stored_base');self.assertEqual([(e.attack,e.health)for e in self.copies(g)],[(2,5)]*2)
        self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].attack,5);self.portable(g)

    def test_current_stored_keeps_temporary_lifetime_base_resets_it(self):
        g=self.game(('cx_temporary','cx_stored','cx_stored_base'),('source',));self.play(g,'cx_temporary')
        original=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id=='body')
        self.assertIsNotNone(original.hand_lifetime);self.play(g,'cx_stored')
        self.assertTrue(all(e.hand_lifetime==original.hand_lifetime for e in self.copies(g)))
        self.play(g,'cx_stored_base');self.assertTrue(all(e.hand_lifetime is None for e in self.copies(g)));self.portable(g)

    def test_stale_stored_and_board_targets_do_not_create_roots(self):
        g=self.game(('cx_stale','body'),('source',));self.play(g,'cx_stale')
        self.assertFalse(g.state.card_summon_history);self.assertTrue(any(e.kind=='zone_target_skipped'for e in g.events));self.portable(g)
        h=self.game(('cx_stale_board',),('source','body'));self.play(h,'cx_stale_board',h.state.players[1].board[1])
        self.assertFalse(h.state.card_summon_history);self.portable(h)

    def test_original_choice_branch_accepts_attributed_copy_in_own_scope(self):
        g=self.game(('cx_wait',),('source','body'));self.play(g,'cx_wait',g.state.players[1].board[1]);self.portable(g)
        self.assertFalse(g.state.card_summon_history);self.choose(g,'ok')
        self.assertEqual(g.state.card_summon_history[-1].plan.total,2);self.portable(g)

    def test_nested_actual_cast_keeps_two_distinct_material_roots(self):
        g=self.game(('cx_current','body'),('source','body','cx_nested_watch'));self.play(g,'cx_current',g.state.players[1].board[1])
        roots=g.state.card_summon_history;self.assertEqual(len(roots),2)
        self.assertEqual([r.request.materials[0].profile for r in roots],['board_copy','stored_copy'])
        self.assertEqual([len(r.deliveries)for r in roots],[2,2]);self.assertNotEqual(roots[0].request.cause.cast_id,roots[1].request.cause.cast_id);self.portable(g)

    def test_terminal_closes_only_actual_copy_prefix(self):
        g=self.game(('cx_current',),('source','body','fatal_watcher'));self.play(g,'cx_current',g.state.players[1].board[1])
        root=g.state.card_summon_history[-1];self.assertEqual((root.status,root.plan.total,len(root.deliveries)),('interrupted',2,1));self.portable(g)

    def test_true_retry_retires_material_root_and_keeps_monotonic_identity(self):
        g=self.game(('cx_retry',),('source','body'));self.play(g,'cx_retry',g.state.players[1].board[1]);self.portable(g)
        old=g.state.card_summon_history[-1];self.choose(g,'retry');self.portable(g)
        self.assertEqual(len(g.state.card_summon_history),1);new=g.state.card_summon_history[-1]
        self.assertGreater(new.id,old.id);self.assertGreater(new.deliveries[0].entity.entity_id,old.deliveries[-1].entity.entity_id);self.portable(g)

    def test_board_awake_current_and_stored_dormancy_are_distinct(self):
        g=self.game(('cx_awake_copy',),('source','cx_dormant'));self.play(g,'cx_awake_copy')
        self.assertTrue(all(e.dormancy is None for e in self.copies(g)));self.portable(g)
        h=self.game(('cx_stored','cx_dormant'),('source',));self.play(h,'cx_stored')
        self.assertTrue(all(e.dormancy is not None for e in self.copies(h)));self.portable(h)

    def test_local_permit_reference_rewrites_but_granted_source_provenance_stays(self):
        g=self.game(('cx_permit',),('source','cx_banned'));original=g.state.players[1].board[1];self.play(g,'cx_permit',original)
        for e in self.copies(g):
            policy=next(a for a in e.abilities if a.kind=='attack_policy');permit=next(a for a in e.abilities if a.kind=='printed_attack_permit')
            self.assertEqual(permit.printed_attack_permit.permitted_ability_id,policy.id)
            self.assertEqual((policy.source_id,permit.source_id),(e.id,original))
        self.portable(g)

    def test_rehashed_material_identity_capture_and_tail_edits_reject(self):
        g=self.game(('cx_current',),('source','body','cx_watch'));self.play(g,'cx_current',g.state.players[1].board[1]);s=self.portable(g)
        for name in ('face','origin','turn','allocator','profile','damage','missing-local','tail'):
            with self.subTest(name=name):
                bad=deepcopy(s);root=bad['state']['card_summon_history'][0];material=root['request']['materials'][0]
                if name=='face':material['card_id']='other'
                elif name=='origin':material['origin']['entity_id']=bad['state']['next_entity_id']
                elif name=='turn':material['captured_turn']+=1
                elif name=='allocator':material['next_attachment_id']+=1
                elif name=='profile':material['profile']='stored_copy'
                elif name=='damage':material['local']['damage']+=1
                elif name=='missing-local':material['local']=None
                else:bad['resolution_frame']['fields']['continuation']['tuple']=[]
                self.reject(bad,name)

    def test_future_copy_choice_target_and_cause_are_rejected_after_rehash(self):
        g=self.game(('cx_wait',),('source','body'));self.play(g,'cx_wait',g.state.players[1].board[1]);s=self.portable(g)
        for name in ('target','cause'):
            bad=deepcopy(s)
            def change(v):
                if type(v)is dict:
                    if str(v.get('type','')).endswith('.CopyMinion'):
                        if name=='target':v['fields']['target_id']=bad['state']['next_entity_id']
                        else:v['fields']['cause']['fields']['action']=bad['state']['action_number']+1
                        return True
                    return any(change(x)for x in v.values())
                if type(v)is list:return any(change(x)for x in v)
                return False
            self.assertTrue(change(bad));self.reject(bad,name)

    def test_legacy_copy_requires_attribution_only_when_quantity_is_active(self):
        g=self.game(('copy',),('body',));self.play(g,'copy',g.state.players[1].board[0]);self.assertFalse(g.state.card_summon_history);self.portable(g)
        h=self.game(('copy',),('source','body'));before=h.snapshot()
        with self.assertRaisesRegex(Exception,'Unattributed summon'):self.play(h,'copy',h.state.players[1].board[1])
        self.assertEqual(h.snapshot(),before)
