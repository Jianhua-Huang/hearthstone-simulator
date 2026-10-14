"""Exactly two new combinations; no legacy TestCase/fixture imports."""
from copy import deepcopy
import json,os,pathlib,unittest
from hs_sim.engine import (AdvanceLocationFace, Attack, AttackPolicySpec, AttackSourceBinding,
    AttackSourcePolicy, CardDefinition, CardType, EndTurn, Game, GrantAttackPolicy,
    HeroAttackQuery, Keyword, LocationFaceReference, MakeHandCardTemporary,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, UseLocation, Zone, hero_attack_count)
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, EquipWeapon, GainArmor,
    RandomDamage, RequestChoice)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference

def find(state,name,zone=Zone.BOARD,player=1):
    return next(e.id for e in state.entities.values() if e.card_id==name and e.zone==zone and e.controller==player)

def registry(mode):
    r=Registry('v141-only-two-new-combinations-'+mode)
    for d in (CardDefinition('hero','hero',CardType.HERO,attack=2,health=100),
              CardDefinition('plain','plain',CardType.MINION,cost=1,attack=1,health=10),
              CardDefinition('actor','actor',CardType.MINION,attack=2,health=8,keywords=(Keyword.CHARGE,))):r.register_card(d)
    def locref(c):
        entity=next(e for e in c.state.entities.values() if e.controller==1 and e.kind==CardType.LOCATION and e.zone==Zone.BOARD)
        return LocationFaceReference.capture(c.state,entity.id)
    def handref(c,name='plain'):return CardReference.capture(c.state.entities[find(c.state,name,Zone.HAND)])
    def on_use(c):
        ref=locref(c);destination={'A':'B','B':'C','C':'A'}[ref.card_id]
        return [RequestChoice(1,(ChoiceOption('face','Face',(AdvanceLocationFace(ref,destination,c.source_id),)),),c.source_id)]
    r.register_behavior('use',on_use)
    for name in ('A','B','C'):
        r.register_card(CardDefinition(name,name,CardType.LOCATION,cost=1,durability=5,on_use='use'))
    def mark(c):
        ref=handref(c,'A')
        return [MakeHandCardTemporary(ref,c.state.turn,source_id=c.source_id),
                RequestChoice(1,(ChoiceOption('continue','Continue'),),c.source_id)]
    def finished(c):
        if c.state.entities[c.event.source_id].kind!=CardType.HERO:return []
        completed=hero_attack_count(c.state,1,HeroAttackQuery())
        ref=locref(c);dest='A' if mode=='natural' else 'C'
        if mode=='natural':
            temp=MakeHandCardTemporary(handref(c),c.state.turn,source_id=c.source_id)
            change=AdvanceLocationFace(ref,dest,c.source_id)
            bad=(temp,change,RandomDamage((c.state.players[2].hero_id,find(c.state,'plain',player=2)),1,c.source_id),EquipWeapon(1,'plain'))
            nested=RequestChoice(1,(ChoiceOption('confirm','Confirm',(temp,change,GainArmor(1,completed))),),c.source_id)
            return [RequestChoice(1,(ChoiceOption('bad','Bad',bad),ChoiceOption('ok','Okay',(nested,))),c.source_id)]
        source=find(c.state,'reborn');actor=find(c.state,'actor')
        bound=GrantAttackPolicy(actor,AttackPolicySpec('cannot_attack'),source_id=source,
            source_binding=AttackSourceBinding.capture(c.state,source,AttackSourcePolicy('active','preserve','ignore')))
        return [RequestChoice(1,(ChoiceOption('bind','Bind',(bound,AdvanceLocationFace(ref,dest,c.source_id),GainArmor(1,completed))),),c.source_id)]
    def health(c):
        if c.event.target_id!=c.state.players[2].hero_id:return []
        source=find(c.state,'reborn')
        return [Damage(source,1,c.source_id),Buff(source,health=-2,source_id=c.source_id)]
    def death(c):
        if hero_attack_count(c.state,1,HeroAttackQuery()):return [GainArmor(1,1)]
        ref=locref(c);temp=MakeHandCardTemporary(handref(c),c.state.turn,source_id=c.source_id)
        declared=hero_attack_count(c.state,1,HeroAttackQuery('declared'))
        return [RequestChoice(1,(ChoiceOption('revive','Revive',(AdvanceLocationFace(ref,'B',c.source_id),temp,GainArmor(1,declared))),),c.source_id)]
    def kill(c):return [Buff(find(c.state,'reborn'),health=-2,source_id=c.source_id)]
    bodies={'mark':mark,'finished':finished,'health':health,'death':death,'kill':kill}
    for name,fn in bodies.items():r.register_behavior(name,fn)
    for name in ('mark','kill'):r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    triggers=(TriggerSpec('attack_finished','finished'),)
    if mode=='death':triggers+=(TriggerSpec('attack_declared','health'),)
    r.register_card(CardDefinition('watch','watch',CardType.MINION,health=30,triggers=triggers))
    r.register_card(CardDefinition('reborn','reborn',CardType.MINION,attack=1,health=2,
        keywords=(Keyword.REBORN,),deathrattle='death'))
    return r

class CombinedMechanismTests(unittest.TestCase):
    def game(self,mode):
        self.mode=mode;self.r=registry(mode);self.index=0
        board=('watch',) if mode=='natural' else ('actor','reborn','watch','A')
        hand=('mark','A','plain') if mode=='natural' else ('plain','kill')
        return Game.from_scenario(Scenario((PlayerSetup('hero',board=board,hand=hand,deck=('plain',)*20,mana=10,max_mana=10),
            PlayerSetup('hero',board=('plain',),deck=('plain',)*20,mana=10,max_mana=10)),seed=141),self.r)
    def stash(self,label,value):
        directory=os.environ.get('HS141_EVIDENCE_DIR')
        if directory:
            self.index+=1;p=pathlib.Path(directory)/self._testMethodName/(str(self.index).zfill(3)+'-'+label+'.json')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))
    def count(self,g,phase='completed'):return hero_attack_count(g.state,1,HeroAttackQuery(phase))
    def select(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def cast(self,g,name):g.apply(PlayCard(1,find(g.state,name,Zone.HAND)))
    def portable(self,g,label):
        snap=json.loads(json.dumps(g.snapshot()));self.stash(label,snap)
        restored=Game.from_snapshot(deepcopy(snap),registry(self.mode))
        self.assertEqual(restored.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),snap)
        return restored
    def private(self,g):
        for p in (1,2):
            text=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for field in ('hero_attack_history','resolution_frame','zone_epoch','entered_order','board_presence_id','source_binding'):
                self.assertNotIn('"'+field+'"',text)
        self.assertFalse(any(e['kind']=='hand_card_made_temporary' for e in g.player_events(2)))
    def reject_joint_frame(self,g):
        original=g.snapshot()
        def objects(v,kind):
            if isinstance(v,dict):
                if v.get('type')==kind:yield v
                for child in v.values():yield from objects(child,kind)
            elif isinstance(v,list):
                for child in v:yield from objects(child,kind)
        for kind,change in (
            ('hs_sim.engine.locations.AdvanceLocationFace',lambda row:row['fields']['target']['fields'].update(zone_epoch=999999)),
            ('hs_sim.engine.temporary_cards.MakeHandCardTemporary',lambda row:row['fields']['card']['fields'].update(entity_id=999999))):
            bad=deepcopy(original);rows=list(objects(bad['resolution_frame'],kind));self.assertTrue(rows)
            for row in rows:change(row)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
            self.stash('rehashed-joint-negative-'+kind.rsplit('.',1)[-1],bad)
            with self.assertRaises(SnapshotError) as error:Game.from_snapshot(bad,registry(self.mode))
            self.assertNotIn('digest mismatch',str(error.exception).lower())
        self.assertEqual(g.snapshot(),original)

    def test_temporary_location_natural_owner_cooldown_then_completed_hero_nested_wait_rollback(self):
        g=self.game('natural');location=find(g.state,'A',Zone.HAND);self.cast(g,'mark')
        self.assertEqual(g.state.entities[location].hand_lifetime.expires_turn,1)
        self.portable(g,'paid-original-mark-wait');self.select(g,'continue');g.apply(PlayCard(1,location))
        g.apply(UseLocation(1,location));self.portable(g,'A-use-wait');self.select(g,'face')
        self.assertEqual((g.state.entities[location].card_id,g.state.entities[location].location_cooldown),('B',2))
        g.apply(EndTurn(1));self.assertIsNone(g.state.entities[location].hand_lifetime)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[location].location_cooldown,1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.entities[location].location_cooldown,0)
        g.apply(UseLocation(1,location));self.portable(g,'natural-B-use-wait');self.select(g,'face')
        self.assertEqual(g.state.entities[location].card_id,'C')
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(self.count(g),1);self.assertEqual(self.count(g,'combat_accepted'),1)
        boundary=g.snapshot();restored=self.portable(g,'completed-hero-mixed-wait');clone=g.clone()
        self.reject_joint_frame(g);self.private(g)
        for branch in (g,restored,clone):
            with self.assertRaises(ResolutionError):self.select(branch,'bad')
            self.assertEqual(branch.snapshot(),boundary)
            self.select(branch,'ok');self.portable(branch,'nested-mixed-confirm-wait');self.select(branch,'confirm')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.assertEqual(g.state.entities[location].card_id,'A');self.assertEqual(self.count(g),1)
        marked=[i for i in g.state.players[1].hand if g.state.entities[i].hand_lifetime]
        self.assertEqual(len(marked),1);self.assertEqual(g.state.entities[marked[0]].hand_lifetime.expires_turn,5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual([dict(e.data)['new_card_id'] for e in g.events if e.kind=='location_face_changed'],['B','C','A'])
        self.private(g);self.portable(g,'final-before-global-expiry');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[marked[0]].zone,Zone.GRAVEYARD)
        self.assertIn(location,g.state.players[1].board);self.assertEqual(self.count(g),1)
        self.portable(g,'final-after-global-expiry')

    def test_signed_death_reborn_wait_preserves_hero_tail_and_two_faces_temporary_bound_source(self):
        g=self.game('death');original=find(g.state,'reborn');location=find(g.state,'A');actor=find(g.state,'actor')
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual((self.count(g,'declared'),self.count(g,'combat_accepted'),self.count(g)),(1,0,0))
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.death_history[-1].cause.kind,'health_state')
        before=g.snapshot();restored=self.portable(g,'declared-hero-signed-death-original-DR-wait');clone=g.clone()
        self.reject_joint_frame(g);self.private(g)
        for branch in (g,restored,clone):
            self.select(branch,'revive')
            self.assertEqual(branch.state.entities[location].card_id,'B')
            self.assertEqual(self.count(branch),1);self.assertIsNotNone(branch.state.pending_choice)
            fresh=find(branch.state,'reborn');self.assertNotEqual(fresh,original)
            self.assertEqual(branch.state.entities[fresh].health,1)
            self.portable(branch,'completed-hero-reborn-new-binding-wait');self.select(branch,'bind')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.assertEqual(g.state.entities[location].card_id,'C');self.assertEqual(self.count(g),1)
        self.assertFalse(any(isinstance(a,Attack) and a.attacker_id==actor for a in g.legal_actions()))
        fresh=find(g.state,'reborn');self.cast(g,'kill');self.assertEqual(g.state.entities[fresh].zone,Zone.GRAVEYARD)
        self.assertTrue(any(isinstance(a,Attack) and a.attacker_id==actor for a in g.legal_actions()))
        self.assertEqual(g.state.entities[actor].attacks_this_turn,0)
        # The first DR armor point is actually debited by hero combat before
        # the completed trigger and second physical source death each add one.
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(self.count(g),1);self.private(g);self.portable(g,'completed-after-bound-source-death')
        marked=find(g.state,'plain',Zone.HAND);g.apply(EndTurn(1));self.assertEqual(g.state.entities[marked].zone,Zone.GRAVEYARD)
        self.assertEqual(self.count(g),1);self.portable(g,'after-both-original-clocks')

if __name__=='__main__':unittest.main()
