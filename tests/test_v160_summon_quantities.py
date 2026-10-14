"""Actual attributed summons, original plans, entry material and waiting tails."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json,os,unittest

from hs_sim.engine import (CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,Registry,Scenario,
    SelectChoice,SnapshotError,SummonByCard,SummonCause,SummonEntryMaterial,SummonQuantitySpec,GrantSummonQuantity,
    TriggerSpec,Zone,RewindSpec,SummonStats,EndTurn,UseHeroPower)
from hs_sim.engine.effects import (Buff,ChoiceOption,Destroy,EquipWeapon,GainArmor,RandomDamage,RequestChoice,
    Silence,Summon,Transform,CopyMinion,ChangeControl,ReturnToHand,Damage)
from hs_sim.engine.summon_quantities import DeliverCardSummon,FinishCardSummon
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


def registry():
    r=Registry('v160-attributed-card-summon-local')
    for c in (
        CardDefinition('hero','Hero',CardType.HERO,health=30),
        CardDefinition('body','Body',CardType.MINION,attack=2,health=5),
        CardDefinition('other','Other',CardType.MINION,attack=3,health=7),
        CardDefinition('source','Quantity source',CardType.MINION,health=5,summon_quantities=(SummonQuantitySpec(),)),
        CardDefinition('double','Two independent rows',CardType.MINION,health=5,summon_quantities=(SummonQuantitySpec(),SummonQuantitySpec())),
        CardDefinition('weapon','Weapon',CardType.WEAPON,attack=2,durability=3),
        CardDefinition('quantity_weapon','Quantity weapon',CardType.WEAPON,attack=2,durability=3,summon_quantities=(SummonQuantitySpec(),)),
        CardDefinition('reborn_source','Reborn source',CardType.MINION,health=5,keywords=(Keyword.REBORN,),summon_quantities=(SummonQuantitySpec(),)),
    ):r.register_card(c)
    r.register_behavior('gift',lambda c:[GainArmor(c.player_id,2)])
    def attributed(c,materials=(SummonEntryMaterial('body'),),selection='first',player=None):
        return SummonByCard(c.player_id if player is None else player,materials,SummonCause.capture(c),selection)
    def watch(c):
        roots=c.state.card_summon_history
        if not roots or not roots[-1].deliveries or roots[-1].deliveries[-1].index!=0:return []
        if c.event.target_id==c.source_id:return []
        sources=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='source']
        return [*(Destroy(i,c.source_id)for i in sources),Buff(c.event.target_id,attack=10,source_id=c.source_id),
            RequestChoice(c.player_id,(ChoiceOption('bad','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(c.player_id,'body'))),
                ChoiceOption('ok','Continue',())),c.source_id)]
    r.register_behavior('watch',watch)
    r.register_card(CardDefinition('watcher','Watch entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','watch'),)))
    r.register_behavior('end_game',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
    r.register_card(CardDefinition('fatal_watcher','Fatal entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','end_game'),)))
    r.register_behavior('death_summon',lambda c:[attributed(c)])
    r.register_card(CardDefinition('death_source','Death summon',CardType.MINION,health=2,deathrattle='death_summon'))
    r.register_behavior('power_summon',lambda c:[attributed(c)])
    r.register_card(CardDefinition('power','Summon power',CardType.HERO_POWER,cost=2,on_use='power_summon'))
    bodies={
        'single':lambda c:[attributed(c)],
        'random':lambda c:[attributed(c,(SummonEntryMaterial('body'),SummonEntryMaterial('other')),'random')],
        'preentry':lambda c:[attributed(c,(SummonEntryMaterial('body',SummonStats(7,3),('gift',),(Keyword.TAUNT,)),))],
        'source_entry':lambda c:[attributed(c,(SummonEntryMaterial('source'),)),attributed(c)],
        'enemy_cast':lambda c:[CastSpell(2,'single',c.source_id,choices='player')],
        'enemy_receive':lambda c:[attributed(c,player=2)],
        'legacy':lambda c:[Summon(c.player_id,'body')],
        'grant':lambda c:[GrantSummonQuantity(c.target_id,SummonQuantitySpec(),c.source_id)],
        'temp':lambda c:[GrantSummonQuantity(c.target_id,SummonQuantitySpec(),c.source_id,c.state.turn)],
        'silence':lambda c:[Silence(c.target_id)],
        'transform':lambda c:[Transform(c.target_id,'body')],
        'kill':lambda c:[Destroy(c.target_id,c.source_id)],
        'copy':lambda c:[CopyMinion(c.target_id,c.player_id)],
        'steal':lambda c:[ChangeControl(c.target_id,2)],
        'bounce':lambda c:[ReturnToHand(c.target_id)],
        'equip_quantity':lambda c:[EquipWeapon(c.player_id,'quantity_weapon')],
        'replace_weapon':lambda c:[EquipWeapon(c.player_id,'weapon')],
        'unknown_entry':lambda c:[attributed(c,(SummonEntryMaterial('unknown'),),'random')],
        'slot':lambda c:[SummonByCard(c.player_id,(SummonEntryMaterial('body'),),SummonCause.capture(c),position=0)],
        'waiting':lambda c:[RequestChoice(c.player_id,(ChoiceOption('ok','Summon',(attributed(c),)),),c.source_id)],
        'control_injection':lambda c:[RequestChoice(c.player_id,(ChoiceOption('bad','Injected',(FinishCardSummon(1),)),),c.source_id)],
        'retry':lambda c:[attributed(c,(SummonEntryMaterial('other'),),'random')],
    }
    for name,fn in bodies.items():
        r.register_behavior(name,fn)
        r.register_card(CardDefinition(name,name,CardType.SPELL,cost=2 if name in ('single','random','preentry')else 0,
            on_play=name,requires_target=name in ('grant','temp','silence','transform','kill','copy','steal','bounce'),
            keywords=(Keyword.REWIND,)if name=='retry'else (),rewind=RewindSpec(1)if name=='retry'else None))
    return r


class SummonQuantityTests(unittest.TestCase):
    def blob(self,g,label):
        if not os.environ.get('V160_INPUT_DIR'):return
        root=Path(os.environ['V160_INPUT_DIR'])/self._testMethodName;root.mkdir(parents=True,exist_ok=True)
        n=getattr(self,'counter',0)+1;self.counter=n
        s=g.snapshot()if hasattr(g,'snapshot')else g
        (root/f'{n:03d}-{label}.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),power=None):
        g=Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,mana=10,max_mana=10,deck=('body',)*5,hero_power_card_id=power),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,mana=10,max_mana=10,deck=('body',)*5)),seed=160),registry())
        self.blob(g,'initial');return g
    def play(self,g,name,target=None):
        self.blob(g,'before-'+name)
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,i,target))
    def choose(self,g,key):
        self.blob(g,'before-'+key);p=g.state.pending_choice
        return g.apply(SelectChoice(p.player_id,p.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('card_summon_history','SummonQuantityPlan','rng_before','rng_after','next_card_summon_id','card_summon_accepted','card_summon_finished'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def reject(self,s,label):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s,label)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
    def test_paid_random_selects_once_and_delivers_independent_same_material(self):
        g=self.game(('random',),('source',));self.play(g,'random')
        root=g.state.card_summon_history[-1]
        self.assertEqual((root.plan.total,len(root.deliveries),root.status),(2,2,'completed'))
        self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len({d.entity.card_id for d in root.deliveries}),1)
        self.assertEqual(len({d.entity.entity_id for d in root.deliveries}),2)
        self.assertEqual(g.snapshot()['rng_state'],list(root.rng_after[:1])+[list(root.rng_after[1]),root.rng_after[2]])
        self.portable(g)
    def test_all_original_rows_and_physical_attachment_product(self):
        g=self.game(('single',),('source','double'),('source',));self.play(g,'single')
        root=g.state.card_summon_history[-1]
        self.assertEqual(root.plan.total,8)
        self.assertEqual([r.eligible for r in root.plan.decisions],[True,True,True,False])
        self.assertEqual([d.outcome for d in root.deliveries],['delivered']*5+['board_full']*3)
        self.portable(g)
    def test_enemy_causing_card_does_not_borrow_receiving_player_multiplier(self):
        g=self.game(('enemy_cast',),('source',));self.play(g,'enemy_cast')
        root=g.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.player_id,root.request.player_id,root.plan.total),(2,2,1))
        self.assertEqual([r.eligible for r in root.plan.decisions],[False]);self.portable(g)
    def test_causing_player_matches_even_when_delivery_recipient_is_enemy(self):
        g=self.game(('enemy_receive',),('source',));self.play(g,'enemy_receive')
        root=g.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.player_id,root.request.player_id,root.plan.total),(1,2,2))
        self.assertEqual(len(g.state.players[2].board),2);self.portable(g)
    def test_preentry_grants_stats_and_independent_deathrattles_on_both_bodies(self):
        g=self.game(('preentry','kill','kill'),('source',));self.play(g,'preentry')
        ids=[d.entity.entity_id for d in g.state.card_summon_history[-1].deliveries]
        for i in ids:
            e=g.state.entities[i];self.assertEqual((e.attack,e.health),(7,3));self.assertIn(Keyword.TAUNT,e.keywords)
            self.assertEqual(len([a for a in e.abilities if a.kind=='deathrattle']),1)
        self.assertNotEqual([a.id for a in g.state.entities[ids[0]].abilities],[a.id for a in g.state.entities[ids[1]].abilities])
        for i in ids:self.play(g,'kill',i)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.portable(g)
    def test_original_source_dies_first_entry_but_extra_template_and_plan_survive_true_wait(self):
        g=self.game(('single',),('source','watcher'));self.play(g,'single')
        self.assertIsNotNone(g.state.pending_choice);s=self.portable(g)
        root=g.state.card_summon_history[-1];first=root.deliveries[0].entity.entity_id
        self.assertEqual((root.plan.total,len(root.deliveries)),(2,1))
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s)
        self.choose(g,'ok');root=g.state.card_summon_history[-1]
        self.assertEqual((g.state.entities[first].attack,g.state.entities[root.deliveries[1].entity.entity_id].attack),(12,2))
        self.assertEqual(root.status,'completed');self.portable(g)
    def test_new_quantity_sources_do_not_recursively_expand_accepted_root(self):
        g=self.game(('source_entry',),('source',));self.play(g,'source_entry')
        roots=g.state.card_summon_history
        self.assertEqual([r.plan.total for r in roots],[2,8])
        self.assertEqual([len(r.deliveries)for r in roots],[2,8])
        self.assertEqual(len(g.state.players[1].board),7);self.portable(g)
    def test_full_board_has_no_candidate_rng_but_still_validates_all_materials(self):
        g=self.game(('random',),('source',)+('body',)*6);before=g.snapshot()['rng_state'];self.play(g,'random')
        root=g.state.card_summon_history[-1]
        self.assertEqual((root.selected,root.status,root.deliveries),(None,'skipped',()))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_silence_and_transform_remove_quantity_then_new_request_recaptures(self):
        for op in ('silence','transform'):
            with self.subTest(op=op):
                g=self.game((op,'single'),('source',));i=g.state.players[1].board[0]
                self.play(g,op,i);self.play(g,'single')
                self.assertEqual(g.state.card_summon_history[-1].plan.total,1);self.portable(g)
    def test_dynamic_quantity_grant_is_separate_row_and_explicit_kind_filter(self):
        g=self.game(('grant','single'),('body',));i=g.state.players[1].board[0]
        self.play(g,'grant',i);self.play(g,'single')
        root=g.state.card_summon_history[-1];a=root.plan.facts[0].abilities[0]
        self.assertEqual((a.origin,root.plan.total),('granted',2));self.portable(g)
        with self.assertRaises(ValueError):SummonQuantitySpec(True)
        with self.assertRaises(ValueError):SummonQuantitySpec(profile='unverified_extra_producer')
    def test_legacy_unattributed_and_unsupported_copy_roll_back_explicitly(self):
        for name in ('legacy','copy'):
            with self.subTest(name=name):
                g=self.game((name,),('source','body'));s=g.snapshot()
                with self.assertRaisesRegex(Exception,'Unattributed summon'):self.play(g,name,g.state.players[1].board[1]if name=='copy'else None)
                self.assertEqual(g.snapshot(),s)
    def test_public_request_saved_in_real_choice_branch_is_restorable(self):
        g=self.game(('waiting',),('source',));self.play(g,'waiting');self.portable(g)
        self.choose(g,'ok');self.assertEqual(g.state.card_summon_history[-1].plan.total,2);self.portable(g)
    def test_current_quantity_proof_mutations_rejected_after_rehash(self):
        g=self.game(('single',),('source','watcher'));self.play(g,'single');s=self.portable(g)
        mutations={
            'crop-row':lambda r:r['plan']['decisions'].clear(),
            'reduce-total':lambda r:r['plan'].update(total=1),
            'foreign-ability':lambda r:r['plan']['decisions'][0].update(ability_id=999999),
            'unknown-entry':lambda r:r['request']['materials'][0].update(card_id='unknown'),
            'wrong-cast':lambda r:r['request']['cause'].update(cast_id=999999),
            'future-allocation':lambda r:r['plan']['facts'][0]['carrier'].update(next_entity_id=999999),
            'RNG-change':lambda r:r['rng_after'][1].__setitem__(2,r['rng_after'][1][2]^1),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                bad=deepcopy(s);mutate(bad['state']['card_summon_history'][0]);self.reject(bad,name)
    def test_choice_cannot_inject_internal_finish(self):
        g=self.game(('control_injection',),('source',));s=g.snapshot()
        with self.assertRaisesRegex(Exception,'inject summon control'):self.play(g,'control_injection')
        self.assertEqual(g.snapshot(),s)
    def test_retry_preserves_monotonic_root_identity_and_discards_old_deliveries(self):
        g=self.game(('retry',),('source',));self.play(g,'retry')
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        first=g.state.card_summon_history[-1].id
        self.choose(g,'retry');self.portable(g)
        self.assertGreater(g.state.card_summon_history[-1].id,first)
        self.assertEqual(len(g.state.card_summon_history),1)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.card_summon_history[-1].status,'completed');self.portable(g)

    def test_control_changes_controller_qualification_but_not_original_owner(self):
        g=self.game(('steal','single'),('source',),enemy_hand=('single',))
        source=g.state.players[1].board[0];self.play(g,'steal',source);self.play(g,'single')
        self.assertEqual(g.state.card_summon_history[-1].plan.total,1);self.portable(g)
        g.apply(EndTurn(1));self.play(g,'single')
        root=g.state.card_summon_history[-1]
        self.assertEqual(root.plan.total,2)
        self.assertEqual((root.plan.facts[0].carrier.owner,root.plan.facts[0].carrier.controller),(1,2));self.portable(g)

    def test_temporary_expiry_and_bounce_follow_shared_attachment_lifecycle(self):
        g=self.game(('temp','single','single'),('body',));source=g.state.players[1].board[0]
        self.play(g,'temp',source);self.play(g,'single');self.assertEqual(g.state.card_summon_history[-1].plan.total,2)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'single')
        self.assertEqual(g.state.card_summon_history[-1].plan.total,1);self.portable(g)
        h=self.game(('bounce','single'),('source',));source=h.state.players[1].board[0]
        self.play(h,'bounce',source);self.play(h,'single')
        self.assertEqual(h.state.card_summon_history[-1].plan.total,1)
        self.assertFalse(h.state.card_summon_history[-1].plan.decisions[0].eligible);self.portable(h)

    def test_weapon_presence_replacement_and_reborn_new_identity(self):
        g=self.game(('equip_quantity','single','replace_weapon','single'))
        self.play(g,'equip_quantity');self.play(g,'single');self.assertEqual(g.state.card_summon_history[-1].plan.total,2)
        self.play(g,'replace_weapon');self.play(g,'single');self.assertEqual(g.state.card_summon_history[-1].plan.total,1);self.portable(g)
        h=self.game(('kill','single'),('reborn_source',));old=h.state.players[1].board[0]
        old_row=next(a.id for a in h.state.entities[old].abilities if a.kind=='summon_quantity');self.play(h,'kill',old)
        new=h.state.players[1].board[0];self.assertNotEqual(old,new)
        self.play(h,'single');root=h.state.card_summon_history[-1]
        self.assertEqual(root.plan.total,2)
        self.assertEqual([(r.carrier_id,r.eligible)for r in root.plan.decisions],[(old,False),(new,True)])
        self.assertNotEqual(old_row,next(r.ability_id for r in root.plan.decisions if r.eligible));self.portable(h)

    def test_deathrattle_cause_and_default_hero_power_exclusion_are_explicit(self):
        g=self.game(('kill',),('source','death_source'));dead=g.state.players[1].board[1]
        self.play(g,'kill',dead);root=g.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.source.entity_id,root.request.cause.origin,root.plan.total),(dead,'card_effect',2));self.portable(g)
        h=self.game(board=('source',),power='power');p=h.state.players[1].hero_power_id
        self.blob(h,'before-power');h.apply(UseHeroPower(1,p));root=h.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.origin,root.request.cause.source.kind,root.plan.total),('hero_power',CardType.HERO_POWER,1));self.portable(h)

    def test_unknown_full_board_candidate_rejects_before_rng_and_allocation(self):
        g=self.game(('unknown_entry',),('source',)+('body',)*6);s=g.snapshot()
        with self.assertRaisesRegex(Exception,'unknown|Unknown'):self.play(g,'unknown_entry')
        self.assertEqual(g.snapshot(),s)

    def test_positions_and_terminal_interruption_use_actual_entry_prefix(self):
        g=self.game(('slot',),('source','other'));self.play(g,'slot');root=g.state.card_summon_history[-1]
        self.assertEqual(g.state.players[1].board[:2],[d.entity.entity_id for d in root.deliveries]);self.portable(g)
        h=self.game(('single',),('source','fatal_watcher'));self.play(h,'single');root=h.state.card_summon_history[-1]
        self.assertEqual((root.status,len(root.deliveries),root.plan.total),('interrupted',1,2))
        self.assertEqual(h.state.status,'finished');self.portable(h)

    def test_original_choice_boundary_rejects_coherent_root_and_queue_truncation(self):
        g=self.game(('single',),('source','watcher'));self.play(g,'single');s=self.portable(g)
        for name in ('drop-next','drop-finish','wrong-index','coherent-reduce','false-terminal'):
            with self.subTest(name=name):
                bad=deepcopy(s);tail=bad['resolution_frame']['fields']['continuation']['tuple']
                if name=='drop-next':tail.pop(0)
                elif name=='drop-finish':tail.pop(1)
                elif name=='wrong-index':tail[0]['fields']['index']=0
                elif name=='false-terminal':bad['state']['card_summon_history'][0]['status']='interrupted'
                else:
                    r=bad['state']['card_summon_history'][0];r['plan']['facts']=[];r['plan']['decisions']=[];r['plan']['total']=1;tail.pop(0)
                self.reject(bad,name)

    def test_closed_receipts_reject_coherent_history_and_actual_event_edits(self):
        g=self.game(('single',),('source',));self.play(g,'single');s=self.portable(g)
        for name in ('reduce-current','remove-history','remove-acceptance','change-closed'):
            with self.subTest(name=name):
                bad=deepcopy(s)
                if name=='reduce-current':
                    r=bad['state']['card_summon_history'][0];r['plan']['facts']=[];r['plan']['decisions']=[];r['plan']['total']=1;r['deliveries']=r['deliveries'][:1]
                elif name=='remove-history':bad['state']['card_summon_history']=[]
                elif name=='remove-acceptance':next(e for e in bad['events']if e['kind']=='card_summon_accepted')['kind']='fake'
                else:
                    e=next(e for e in bad['events']if e['kind']=='card_summon_finished');e['amount']=1
                self.reject(bad,name)
