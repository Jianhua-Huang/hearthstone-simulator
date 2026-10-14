"""Local U63 fatal episodes, real queue barriers, no real-card adapter."""
from copy import deepcopy
from dataclasses import replace
import json,os,pathlib,unittest
from hs_sim.engine import (Attack,CardDefinition,CardType,CostSpec,DeathrattleRepeatSpec,Game,HeroAttackQuery,Keyword,PlayCard,PlayerSetup,Registry,Resource,UseHeroPower,hero_attack_count,
    RewindSpec,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone,RecoverHero,SpendUpToResource)
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,Damage,DamageBatch,Destroy,EquipWeapon,GainArmor,GainResource,
    GrantDeathrattle,Heal,RandomDamage,ReplaceHero,RequestChoice)
from hs_sim.engine.resource_operations import resource_result
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.rewind import COUNTERS

def registry():
    r=Registry('v144-local-Hero-lethal-policy')
    def result(c):
        value=c.resource_result
        return [RecoverHero(value.hero_lethal_reference,value.actual_amount)] if value.actual_amount else []
    def spend(c,cap=20):return SpendUpToResource(c.player_id,Resource.CORPSES,cap,c.source_id,'result','hero_lethal_at_debit',c.hero_lethal)
    def choose(c):
        ref=c.hero_lethal
        bad=(GainResource(c.player_id,Resource.CORPSES,2),RandomDamage(tuple(c.state.players[p].hero_id for p in (1,2)),1,c.source_id),EquipWeapon(c.player_id,'plain'))
        return [RequestChoice(c.player_id,(ChoiceOption('save','save',(spend(c),)),ChoiceOption('bad','bad',bad)),c.source_id)]
    def fatal(c):return [Damage(c.state.players[1].hero_id,99,c.source_id)]
    def both(c):return [DamageBatch(tuple(Damage(c.state.players[p].hero_id,99,c.source_id) for p in (1,2)))]
    def board(c):return [DamageBatch((Damage(c.state.players[1].hero_id,99,c.source_id),Damage(c.state.players[1].board[-1],99,c.source_id)))]
    def chain(c):return [RecoverHero(c.hero_lethal,4),Damage(c.state.players[c.player_id].hero_id,99,c.source_id)]
    def chain_choice(c):return [RequestChoice(c.player_id,(ChoiceOption('save','save',tuple(chain(c))),),c.source_id)]
    def armor_reaction(c):return [GainArmor(c.player_id,1)]
    def install(c):return [GrantDeathrattle(c.state.players[1].hero_id,'save3',c.source_id)]
    bodies={'result':result,'save':lambda c:[spend(c)],'save0':lambda c:[spend(c,0)],'save3':lambda c:[spend(c,3)],'choice':choose,'chain_choice':chain_choice,
      'fatal':fatal,'both':both,'board':board,'chain':chain,'install':install,
      'replace':lambda c:[ReplaceHero(c.player_id,'newhero',health=10),RecoverHero(c.hero_lethal,5)],
      'heal':lambda c:[Heal(c.state.players[c.player_id].hero_id,105,c.source_id)],
      'doom':lambda c:[Destroy(c.state.players[1].hero_id,c.source_id)],
      'ordinary':lambda c:[SpendUpToResource(c.player_id,Resource.CORPSES,3,c.source_id,'result')],
      'env':lambda c:[AddCostModifier(1,CostSpec(delta=-1,card_types=(CardType.SPELL,)),source_id=c.source_id,expires_turn=c.state.turn+10)],
      'board_dr_choice':lambda c:[RequestChoice(c.player_id,(ChoiceOption('armor','armor',(GainArmor(c.player_id,5),)),),c.source_id)],
      'outside':lambda c:[SpendUpToResource(1,Resource.CORPSES,1,c.source_id,'result','hero_lethal_at_debit',c.state.hero_lethal_history[-1].reference)],
      'armor_reaction':armor_reaction,'corpse_reaction':lambda c:[GainResource(1,Resource.CORPSES,10)] if 'death_id' in dict(c.event.data) else []}
    for n,fn in bodies.items():r.register_behavior(n,fn)
    for n in ('save','save0','save3','choice','chain','chain_choice','replace','heal','ordinary'):
        r.register_card(CardDefinition('hero_'+n,n,CardType.HERO,health=10,attack=10,deathrattle=n))
    r.register_card(CardDefinition('hero','hero',CardType.HERO,health=10))
    r.register_card(CardDefinition('newhero','newhero',CardType.HERO,health=10))
    r.register_card(CardDefinition('plain','plain',CardType.MINION,health=1))
    r.register_card(CardDefinition('axe','axe',CardType.WEAPON,attack=10,durability=2))
    r.register_card(CardDefinition('hp','hp',CardType.HERO_POWER,cost=2,on_use='fatal'))
    r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=100,deathrattle_repeats=(DeathrattleRepeatSpec(3,kinds=(CardType.HERO,)),)))
    r.register_card(CardDefinition('fragile_dr','fragile_dr',CardType.MINION,health=1,deathrattle='board_dr_choice',keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition('watch','watch',CardType.MINION,health=100,triggers=(TriggerSpec('resource_spent','armor_reaction'),TriggerSpec('resource_gained','corpse_reaction'))))
    for n in ('fatal','both','board','install','doom','env','outside'):r.register_card(CardDefinition(n,n,CardType.SPELL,cost=1,on_play=n))
    r.register_card(CardDefinition('retry','retry',CardType.SPELL,cost=1,on_play='fatal',keywords=(Keyword.REWIND,),rewind=RewindSpec(1)))
    return r

class HeroLethalTests(unittest.TestCase):
    def game(self,hero='hero_save',enemy='hero',hand=('fatal',),board=(),balance=5,other=5,weapon=None,power=None):
        self.index=0
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('plain',)*6,mana=10,max_mana=10,corpses=balance,weapon_card_id=weapon,hero_power_card_id=power),
            PlayerSetup(enemy,deck=('plain',)*6,mana=10,max_mana=10,corpses=other)),seed=144),registry())
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def cast(self,g,name='fatal'):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name);g.apply(PlayCard(1,source));return source
    def choose(self,g,key='save'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def stash(self,label,value):
        folder=os.environ.get('HS144_EVIDENCE_DIR')
        if folder:
            self.index+=1;p=pathlib.Path(folder)/self._testMethodName/(f'{self.index:03}-'+label+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))
    def portable(self,g,label='waiting'):
        snap=json.loads(json.dumps(g.snapshot()));self.stash(label,snap)
        self.assertEqual(Game.from_snapshot(deepcopy(snap),registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
        return snap
    def private(self,g):
        for p in (1,2):
            value=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('hero_lethal_roots','hero_lethal_history','episode_id','root_id','zone_epoch','source_allocation','parked_hashes','balance_before','resource_operations'):
                self.assertNotIn('"'+key+'"',value)
    def reject(self,snap,label):
        snap['events_hash']=canonical_hash(snap['events']);snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});self.stash(label,snap)
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,registry())
        self.assertNotIn('digest mismatch',str(error.exception).lower())

    def test_actual_zero_positive_and_same_batch_corpse_then_parked_reactions(self):
        for balance in (0,1,5):
            with self.subTest(balance=balance):
                g=self.game(balance=balance);physical=self.hero(g);self.cast(g)
                self.assertEqual(self.hero(g),physical);self.assertEqual(g.state.status,'playing' if balance else 'finished')
                values=[resource_result(e) for e in g.events if resource_result(e) is not None];self.assertEqual(values[0].actual_amount,balance)
                if balance:self.assertEqual(g.state.entities[physical].health,balance)
                self.portable(g,'final');self.private(g)
        g=self.game(hand=('board',),board=('watch','plain'),balance=0);self.cast(g,'board')
        self.assertEqual(g.state.entities[self.hero(g)].health,1);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],10)
        self.assertEqual(g.state.entities[self.hero(g)].armor,1)
        kinds=[e.kind for e in g.events];self.assertLess(kinds.index('minion_died'),kinds.index('hero_died'));self.assertLess(kinds.index('hero_recovered'),kinds.index('armor_gained'))
        self.assertEqual([d.zone for d in g.state.death_history],[Zone.BOARD,Zone.HERO]);self.portable(g,'corpse-final')

    def test_real_dying_choice_restore_clone_replay_rng_rollback_and_privacy(self):
        g=self.game(hero='hero_choice');self.cast(g);self.assertLessEqual(g.state.entities[self.hero(g)].health,0)
        snap=self.portable(g);self.private(g)
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),snap);self.choose(g);self.assertEqual(g.state.entities[self.hero(g)].health,5);self.portable(g,'final');self.private(g)

    def test_both_heroes_siblings_save_fail_and_child_preserves_other_opportunity(self):
        for left,right in ((0,0),(5,0),(0,5),(5,5)):
            with self.subTest(left=left,right=right):
                g=self.game(enemy='hero_save',hand=('both',),balance=left,other=right);self.cast(g,'both')
                self.assertEqual(g.state.status,'playing' if left and right else 'draw' if not left and not right else 'finished')
                self.assertEqual(len(g.state.hero_lethal_history),2);self.assertTrue(all(e.phase=='finished' for e in g.state.hero_lethal_history));self.portable(g,'dual-final')
        g=self.game(hero='hero_chain',enemy='hero_save',hand=('both',));self.cast(g,'both')
        self.assertEqual(g.state.winner,2);self.assertEqual(g.state.entities[self.hero(g,2)].health,5)
        rows=g.state.hero_lethal_history;self.assertEqual(len(rows),3);self.assertEqual(rows[2].parent_id,rows[0].reference.episode_id)
        self.assertEqual(len([e for e in g.events if e.kind=='game_ended']),1);self.portable(g,'child-final')

    def test_dynamic_stacked_once_plain_heal_doom_replace_and_unsupported_profile(self):
        g=self.game(hero='hero_save3',hand=('install','fatal'),balance=5);self.cast(g,'install');self.cast(g)
        values=[resource_result(e).actual_amount for e in g.events if resource_result(e) is not None];self.assertEqual(values,[3,2])
        self.assertEqual(g.state.entities[self.hero(g)].health,3);self.assertEqual(len(g.state.hero_lethal_history),1);self.portable(g,'stacked')
        g=self.game(hero='hero_heal');self.cast(g);self.assertEqual(g.state.status,'playing');self.assertTrue(g.state.hero_lethal_history[0].recovered);self.portable(g,'heal')
        g=self.game(hand=('doom',));self.cast(g,'doom');self.assertFalse(g.state.entities[self.hero(g)].doomed);self.assertEqual(g.state.entities[self.hero(g)].health,5);self.portable(g,'doom')
        g=self.game(hero='hero_replace');old=self.hero(g);self.cast(g);self.assertNotEqual(self.hero(g),old);self.assertEqual(g.state.entities[self.hero(g)].health,10);self.portable(g,'replace')
        g=self.game(hero='hero_ordinary');before=g.snapshot()
        with self.assertRaisesRegex(Exception,'after_resource_reactions'):self.cast(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(balance=20);before=g.snapshot()
        with self.assertRaisesRegex(Exception,'above current maximum'):self.cast(g)
        self.assertEqual(g.snapshot(),before)

    def test_no_hero_deathrattle_preserves_immediate_terminal(self):
        g=self.game(hero='hero');self.cast(g);self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.hero_lethal_history,[]);self.portable(g,'original-terminal')

    def test_rehashed_tail_plan_reference_and_idle_dead_hero_rejected(self):
        g=self.game(hero='hero_choice',board=('watch',));self.cast(g);snap=self.portable(g)
        # Every mutation reaches semantic validation after both hashes change.
        for name in ('marker','finish','park','future','foreign','plan'):
            value=deepcopy(snap);frame=value['resolution_frame']['fields'];state=value['state']
            work=frame['continuation']['tuple']
            if name in ('marker','finish'):
                typename='FinishHeroLethalRoot' if name=='marker' else 'FinishHeroLethalEpisode';work[:]=[w for w in work if not w.get('type','').endswith(typename)]
            elif name=='park':
                marker=next(i for i,w in enumerate(work) if w.get('type','').endswith('FinishHeroLethalRoot'));del work[marker+1]
            elif name=='future':state['hero_lethal_history'][0]['reference']['episode_id']=999999
            elif name=='foreign':frame['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']['hero_lethal_reference']['fields']['player_id']=2
            else:state['deathrattle_batches'][0]['payloads']=[]
            self.reject(value,name)
        value=deepcopy(snap);value['state']['pending_choice']=None;value['resolution_frame']=None;self.reject(value,'idle')

    def test_paid_rewind_keeps_hero_and_resource_allocators_monotonic(self):
        self.assertIn('next_hero_lethal_id',COUNTERS)
        g=self.game(hero='hero_choice',hand=('retry',));self.cast(g,'retry');self.choose(g)
        self.portable(g,'rewind-first');choice=g.state.pending_choice
        retry=next(o.id for o in choice.options if 'retry' in o.id.lower());self.choose(g,retry)
        self.choose(g);self.portable(g,'rewind-second');self.assertIsNone(g.state.pending_choice)
        ids=[resource_result(e).operation_id for e in g.events if resource_result(e) is not None]
        self.assertEqual(ids,[1,2]);self.assertGreater(g.state.next_hero_lethal_id,4);self.assertEqual(len(g.state.play_history),1);self.portable(g,'rewind-final')

    def test_no_payload_sibling_and_recovered_then_child_have_real_dual_waiting(self):
        g=self.game(hero='hero_choice',enemy='hero',hand=('both',));self.cast(g,'both')
        self.assertEqual(len(g.state.hero_lethal_history),2);self.assertIsNone(g.state.hero_lethal_history[1].group_id)
        self.portable(g,'no-payload-sibling-waiting');self.choose(g);self.assertEqual(g.state.winner,1);self.portable(g,'no-payload-sibling-final')
        g=self.game(hero='hero_chain_choice',enemy='hero_choice',hand=('both',));self.cast(g,'both');self.portable(g,'parent-waiting')
        self.choose(g);self.assertEqual(g.state.pending_choice.player_id,2);self.assertEqual(g.state.status,'playing')
        self.assertEqual(len(g.state.hero_lethal_history),3);child=g.state.hero_lethal_history[2];self.assertEqual(child.phase,'finished');self.assertFalse(child.recovered)
        self.assertEqual(child.parent_id,g.state.hero_lethal_history[0].reference.episode_id)
        self.portable(g,'other-original-Hero-waiting-after-child');self.private(g);self.choose(g)
        self.assertEqual(g.state.winner,2);self.assertEqual(len([e for e in g.events if e.kind=='game_ended']),1);self.portable(g,'only-outer-terminal')

    def test_voluntary_hero_attack_intrinsic_finish_and_hero_power_original_tail(self):
        g=self.game(hero='hero_choice',enemy='hero_save',hand=('env','plain'),weapon='axe',power='hp')
        self.cast(g,'env');before=g.state.players[1];oldhero=self.hero(g);weapon=before.weapon_id;power=before.hero_power_id
        modifiers=deepcopy(before.cost_modifiers);clock=deepcopy(g.state.owner_turn_history);deck=tuple(before.deck);hand=tuple(before.hand)
        g.apply(Attack(1,oldhero,self.hero(g,2)));self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery('completed')),1);self.portable(g,'original-combat-waiting')
        self.assertEqual(g.state.entities[weapon].durability,1)
        kinds=[e.kind for e in g.events];self.assertLess(kinds.index('attack_finished'),kinds.index('hero_died'))
        self.choose(g);self.assertEqual(g.state.status,'playing');self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery('completed')),1)
        after=g.state.players[1];self.assertEqual((after.hero_id,after.weapon_id,after.hero_power_id),(oldhero,weapon,power))
        self.assertEqual(g.state.entities[weapon].durability,1);self.assertEqual(after.cost_modifiers,modifiers);self.assertEqual(tuple(after.deck),deck);self.assertEqual(tuple(after.hand),hand)
        self.assertEqual(g.state.owner_turn_history,clock);self.portable(g,'combat-finished')
        g=self.game(hero='hero_choice',power='hp');power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,power));self.portable(g,'original-power-waiting')
        self.assertFalse(g.state.hero_power_history[-1].completed);self.choose(g);self.assertTrue(g.state.hero_power_history[-1].completed)
        self.assertEqual(g.state.entities[power].uses_this_turn,1);self.assertEqual(g.state.players[1].mana,8);self.portable(g,'power-finished')

    def test_hero_recipient_repeat_plan_and_zero_cap_do_not_repeat_consumed_life(self):
        g=self.game(hero='hero_save0',balance=5);self.cast(g);self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.players[1].resources[Resource.CORPSES],5)
        self.assertEqual(next(resource_result(e) for e in g.events if resource_result(e) is not None).actual_amount,0);self.portable(g,'zero-cap')
        g=self.game(hero='hero_choice',board=('repeat',),balance=9);self.cast(g);self.portable(g,'repeat-first')
        batch=g.state.deathrattle_batches[0];self.assertEqual(batch.total,3);self.assertEqual(batch.payloads[0].plan.repetitions,3)
        for index in range(3):
            self.choose(g)
            if index<2:self.portable(g,'repeat-extra-'+str(index))
        self.assertEqual([x.completed for x in g.state.deathrattle_history],[True,True,True]);self.assertEqual(len(g.state.hero_lethal_history),1)
        self.assertEqual(g.state.entities[self.hero(g)].health,9);self.assertTrue(all(a.consumed for a in g.state.entities[self.hero(g)].abilities if a.kind=='deathrattle'))
        self.portable(g,'repeat-final')

    def test_rehashed_episode_finish_before_its_original_deathrattle_tail_rejected(self):
        g=self.game(hero='hero_choice',enemy='hero_choice',hand=('both',));self.cast(g,'both');snap=self.portable(g,'dual-original')
        work=snap['resolution_frame']['fields']['continuation']['tuple']
        index=next(i for i,w in enumerate(work) if w.get('type','').endswith('FinishHeroLethalEpisode'))
        moved=work.pop(index);work.insert(0,moved)
        self.reject(snap,'Hero-finish-before-original-DR-completion')

    def test_same_batch_minion_deathrattle_reborn_and_original_hero_result_waiting_scopes(self):
        g=self.game(hero='hero_choice',board=('fragile_dr',),hand=('board',),balance=0);self.cast(g,'board')
        self.assertEqual(g.state.players[1].board,[]);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(g.state.pending_choice.source_id,self.hero(g));self.portable(g,'Hero-before-ordinary-DR-Reborn')
        self.choose(g);self.assertEqual(g.state.status,'playing');self.assertIsNone(g.state.active_hero_lethal_root_id)
        self.assertEqual(g.state.pending_choice.source_id,g.state.death_history[0].entity_id);self.assertEqual(g.state.players[1].board,[])
        self.portable(g,'ordinary-DR-after-Hero-root-with-original-dead-captured-context');self.choose(g,'armor')
        self.assertEqual(g.state.entities[self.hero(g)].health,1);self.assertEqual(g.state.entities[self.hero(g)].armor,5)
        self.assertEqual(len(g.state.players[1].board),1);self.assertNotEqual(g.state.players[1].board[0],g.state.death_history[0].entity_id)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.portable(g,'Reborn-after-both-original-groups')

    def test_complete_simultaneous_consumption_active_domain_and_closed_future_facts_rejected(self):
        g=self.game(hero='hero_choice',enemy='hero_choice',hand=('both',));self.cast(g,'both');snap=self.portable(g,'simultaneous')
        for name in ('truncated_simultaneous','reversed_consumption','bool_root','future_reference'):
            value=deepcopy(snap)
            if name=='truncated_simultaneous':value['state']['hero_lethal_roots'][0]['simultaneous'].pop()
            elif name=='reversed_consumption':
                hero=value['state']['entities'][str(self.hero(g))];next(a for a in hero['abilities'] if a['kind']=='deathrattle')['consumed']=False
            elif name=='bool_root':value['state']['active_hero_lethal_root_id']=True
            else:value['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']['hero_lethal_reference']['fields']['episode_id']=999999
            self.reject(value,name)
        self.choose(g);self.assertEqual(g.state.pending_choice.player_id,2);self.choose(g);final=self.portable(g,'both-saved')
        value=deepcopy(final);event=next(e for e in value['events'] if e['kind']=='hero_died');next(x for x in event['data']['episode'] if x[0]=='episode_id')[1]=999999;self.reject(value,'closed-future-Hero-event')
        g=self.game(hero='hero_choice',hand=('fatal','outside'));self.cast(g);self.choose(g);before=g.snapshot()
        with self.assertRaisesRegex(Exception,'genuinely active'):self.cast(g,'outside')
        self.assertEqual(g.snapshot(),before)
        g=self.game(hero='hero_heal',hand=('doom',));self.cast(g,'doom');self.assertEqual(g.state.status,'finished');self.assertTrue(g.state.entities[self.hero(g)].doomed);self.portable(g,'Heal-does-not-clear-Doom')
